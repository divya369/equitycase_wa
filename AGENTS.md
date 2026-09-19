# AGENTS.md — Equity Case WhatsApp Backend

Rules for anyone (human or AI) changing this repo. **Follow the existing
structure exactly. Do not introduce a second way of doing something that
already has a way here.**

## What this is

FastAPI backend for an existing Flutter client: a **single-tenant** WhatsApp
inbox. One WhatsApp Business number (seeded), one operator (seeded), no signup.
"Contacts" are customers who message the business number. There is no
`owner_id` anywhere.

Stack: Python 3.14 · FastAPI · SQLModel (SQLAlchemy 2 async + asyncpg) ·
Alembic · Postgres 16 (docker) · Meta WhatsApp Cloud API · FCM · Cloudflare R2
(S3 API) · structlog · uv.

## Commands

```
make up / down / down-v / logs / psql        # Postgres in docker
make migration m="describe change"           # autogenerate a revision
make migrate / downgrade / downgrade-base    # upgrade head / -1 / base
make history / current
make seed                                    # idempotent singleton rows
make dev                                     # reload, ONE worker
make start                                   # ONE worker
make webhook-sample [kind= status= wamid=]   # signed body for api.rest
make lint / format / check / test
```

Run `make check` before calling any change done.

## Layout

```
src/
  main.py                 app: middleware, error handlers, register_routes, lifespan
  routes.py               the ONLY place routers are registered
  config/                 settings (app_config, database_config, seed_config), lifespan, logging
  core/                   shared infra: database, responses, columns, time, security, deps
  errors/                 codes.py, exceptions.py, handlers.py, responses.py
  middlewares/            request_id
  integrations/           external APIs: meta/, fcm/, storage/, sms/
  realtime/               websocket manager + /ws router
  modules/<feature>/      one package per feature (see below)
  db/models.py            imports every table model for Alembic
  scripts/                one-off CLIs (seed)
migrations/               Alembic (async). versions/ is ruff-excluded.
```

### Module pattern — every feature looks like this

```
modules/<feature>/
  models.py        SQLModel tables (table=True). No logic.
  schemas.py       Pydantic request/response models. The JSON contract lives here.
  repository.py    SQL only. Takes AsyncSession. Returns models. No HTTP, no AppError.
  service.py       Business rules. Calls repositories + integrations. Raises AppError subclasses.
  router.py        Thin: parse input -> call service -> wrap in ApiResponse. No SQL, no rules.
  dependencies.py  Depends() wiring that builds services/repositories.
```

- Call direction is one way: **router -> service -> repository**. A router
  never touches a repository or the session directly; a repository never
  raises HTTP-level errors.
- A service may use another module's repository or service; never import
  another module's router.
- **Transactions: services own them.** Repositories only `flush()`; the
  service calls `session.commit()` / `rollback()` once per use case.
- `dependencies.py` builds the service with its repositories and exposes an
  `Annotated` alias (`AuthServiceDep`, `OperatorServiceDep`). Use
  `SessionDep` from `core.database`, never a raw `Depends(get_session)`.
- The logged-in operator: `operator: CurrentOperator` (from
  `modules.auth.dependencies`).
- New table -> add its import to `src/db/models.py`, then `make migration`.
- New router -> register it in `src/routes.py`: public auth routes on
  `v1_router`, **everything else on `protected_router`** (JWT enforced there,
  once, for all routes — don't add per-route auth).

## Imports

- `src/` is on the path (Makefile `PYTHONPATH`, uvicorn `--app-dir src`,
  alembic `prepend_sys_path`, pytest `pythonpath`).
- Bare absolute imports only: `from errors.exceptions import NotFoundError`,
  `from modules.chats.service import ChatService`.
- **No** relative imports (ruff bans them). **No** `src.` prefix.

## Response standard (all JSON routes)

Success — `core/responses.py`:
```json
{"data": <payload>, "meta": {"request_id": "..."}}
```
Error — `errors/responses.py` (produced only by the registered handlers):
```json
{"errors": {"code": "not_found", "message": "...", "request_id": "...", "details": ...}}
```

- Every JSON route declares `response_model=ApiResponse[T]` and returns
  `ApiResponse(data=..., meta=meta)` with `meta: MetaDep`. Lists are
  `ApiResponse[list[T]]`.
- `204 No Content` routes return no body (no envelope).
- Raise an `AppError` subclass from `errors/exceptions.py`. **Never**
  `HTTPException` (ruff bans it), never build error JSON by hand.
- Error codes are lowercase snake_case in `errors/codes.py`. A new error =
  new code in `ErrorCode` + new exception class in `exceptions.py`.
- Existing: `validation_error` 422, `not_found` 404, `unauthorized` 401,
  `forbidden` 403, `conflict` 409, `conversation_window_closed` 409,
  `invalid_otp` 401, `rate_limited` 429, `bad_gateway` 502,
  `service_unavailable` 503, `internal_error` 500.
- **Exempt from the envelope** (external contracts): Meta webhook
  `GET /webhook` (plain-text `hub.challenge`) and `POST /webhook` (always
  200); WebSocket frames use `{"type","data","ts"}`.

## Routes

- All app APIs live under `/v1`. Auth lives under **`/v1/auth/*`**
  (`/v1/auth/otp/request`, `/v1/auth/otp/verify`, `/v1/auth/logout`).
- Every `/v1` route except `/v1/auth/otp/*` requires the operator JWT.
- Outside /v1: `GET /healthz`, `GET|POST /webhook` (signature-verified, no
  JWT), `/ws?token=<jwt>`.

## JSON contract (the Flutter Dart models parse these — do not rename keys)

The payload inside `data` must match exactly:

- **user** (operator AND contacts): `wa_id, name, phone, avatar_url, about,
  is_online, last_seen`. `is_online` is always `false`, `last_seen` always
  `null` — the Cloud API has no presence. Never fabricate it.
- **message**: `id, chat_id, from, type, text{body}, timestamp, status,
  media_url, context{id}|null, client_msg_id`, plus `error{code,title}` when
  failed.
  - `from` is a Python keyword: `from_: str = Field(alias="from")` with
    `ConfigDict(populate_by_name=True)`. FastAPI serialises by alias — keep it.
  - `timestamp` is **unix seconds as a string** (`core.time.to_unix_str`).
  - `status` is the string label (`MessageStatus(...).label`).
- **chat**: `id, contact{user}, last_message{message}|null, unread_count,
  is_pinned, is_muted`.
- Keep null keys. Never set `response_model_exclude_none`.
- Build these shapes only via the shared schemas' mappers (`UserOut`,
  `MessageOut`, `ChatOut`) so REST, webhook and WS emit identical JSON.

## Database

- SQLModel tables with explicit `sa_column=`; use `core/columns.py`
  factories (`uuid_pk_column`, `timestamp_column`, `text_column`). Set a
  Python default on the Field AND a server default on the column.
- Name every constraint/index explicitly (`uq_`, `ck_`, `ix_`, `fk_`).
- No ORM relationships / lazy loading — repositories query explicitly.
- Migrations: `make migration m="..."`, then **read and fix the generated
  file** before `make migrate`. Verify with `make downgrade` + `make migrate`
  and `uv run alembic check`. Never edit a migration that was already applied
  anywhere shared — add a new one.
- Timestamps are `timestamptz`, always UTC (`core.time.utcnow()`).
- Request handlers use the `get_session` dependency. **Background tasks and
  webhook processing open their own session** via `SessionFactory()` — never
  reuse a request session after the response.

### Invariants (non-negotiable)

- **Message status is monotonic**: `0 pending < 1 sent < 2 delivered < 3 read
  < 4 failed`, updated only with `... WHERE status < :new`. Meta delivers
  webhooks out of order. The ONLY backwards move is
  `POST /v1/messages/{id}/retry` (4 -> 0).
- **POST messages is idempotent** on `(chat_id, client_msg_id)`: catch the
  unique violation and return the existing row.
- Inbound messages are stored as `delivered` (2); set `read` (3) + Meta
  mark-read only when the operator opens the chat.
- `business_number` and `operator` are singleton rows (`id = 1`), created only
  by `make seed`. The app refuses to start without them.

## Meta WhatsApp Cloud API

- **24h window**: free-form sends only within 24h of `chats.last_inbound_at`,
  else `ConversationWindowClosedError` (409). Map Meta error `131047` to the
  same error.
- No customer presence, no inbound typing. Outbound typing is sent with
  mark-read (verify payload against current Meta docs first).
- One shared `httpx.AsyncClient` (created in lifespan), 10s timeout. Retry
  429/5xx with exponential backoff (3 attempts). Never retry 4xx.
- Customers message first; a new contact is a DB row only. Identity is
  `wa_id` = E.164 digits without `+`. Phone input uses `core.phone.PhoneStr`;
  convert with `to_wa_id()` / `to_display_phone()` — never re-implement
  digit stripping.
- **Webhook POST order**: `await request.body()` raw bytes (no Pydantic body
  param) -> `hmac.compare_digest` on `X-Hub-Signature-256` with
  `META_APP_SECRET` (403 on mismatch) -> insert `webhook_events`
  (`msg:<wamid>` / `status:<wamid>:<status>`, `ON CONFLICT DO NOTHING`) ->
  return 200 -> process in background. Replay `processed_at IS NULL` rows on
  startup.
- Webhook code: `modules/webhook/` — `service.py` (handshake, signature,
  `extract_events`, persist), `processor.py` (`WebhookProcessor`: applies
  events, each in its own session; returns False to leave an event for a
  later retry). Events for another `phone_number_id` are ignored.
- Inbound messages: `modules/webhook/inbound.py` (`InboundMessageHandler`,
  lives in the webhook module to avoid a messages <-> webhook import cycle).
  The chat row is locked (`get_by_contact_for_update`) while a message is
  applied. `created_at` = Meta's timestamp (drives `last_inbound_at`, so old
  replays never reopen the 24h window). Message `type` must be one the
  Flutter client renders (`text|image|video|audio|document|sticker|location`);
  anything else is stored as text; reactions/system are skipped. A webhook
  profile name only replaces a placeholder name (the phone / wa_id), never
  one the operator chose.
- `POST /v1/chats/{id}/read`: local state commits first; the Meta mark-read
  (newest inbound wamid, only when something newly became read) is
  best-effort — logged on failure, never raised.
- A status whose wamid we don't know yet waits (it may have beaten our own
  send commit; `MessageDelivery` re-runs pending statuses after storing the
  wamid) and is dropped after `UNMATCHED_STATUS_TTL` (1h).
- Manual webhook tests: `api.rest` (VS Code REST Client) +
  `make webhook-sample`. The body is signed byte-for-byte — never edit
  `.webhook/body.json` by hand.
- Media URLs from Meta expire in ~5 min: download immediately, store in R2,
  serve signed URLs. Bucket stays private.

## OTP / Auth

- OTP is delivered by **SMS (SMSForYou)** through an `OtpSender` in
  `integrations/sms/` — not a WhatsApp template. `SmsForYouSender` is used
  when `SMS_API_URL`, `SMS_API_KEY` and `SENDER_ID` are all set. The message
  text is the DLT-approved template (`OTP_MESSAGE`) — change it only together
  with DLT. Sent once, never retried. The request URL holds the key and code,
  so httpx request logging stays at WARNING.
- argon2 hash at rest, 5-minute expiry, max 5 attempts, newest unconsumed code
  wins, rate-limited by IP (slowapi) on request AND verify.
- Unknown phone on `otp/request` -> still 204, send nothing.
- `DEV_STATIC_OTP` is dev-only; the app refuses to start with it when
  `APP_ENV=production`.
- JWT `sub="operator"`, signed with `JWT_SECRET`, TTL `JWT_TTL_HOURS`.

## Realtime & push

- `/ws?token=`: validate JWT **before** `accept()`; bad token -> close 1008
  (over the wire that is a rejected handshake, HTTP 403). Keep a set of
  sockets; drop any socket that errors during broadcast. Client `ping` ->
  `pong`; 60s without any frame -> close 1000.
- Code: `realtime/manager.py` (`ws_manager`, `WsEvent`), `realtime/events.py`
  (builders — payloads come from `MessageOut`/`ChatOut`, never hand-built),
  `realtime/router.py`.
- **Publish only after the commit.** Services publish right after
  `session.commit()`; `WebhookProcessor` collects the events of one webhook
  event (`InboundMessageHandler.events`) and publishes after its commit.
  A failed / no-op change (duplicate, stale status, idempotent resend)
  publishes nothing.
- Events: inbound -> `message.new` + `chat.updated`; status change / send
  result / retry -> `message.status` (`id, wamid, status, client_msg_id`,
  plus `chat_id`, `error`); send / read / clear -> `chat.updated`; message
  delete -> `message.deleted` (+ `chat.updated` if it was the last);
  chat or contact delete -> `chat.deleted`.
- Tests: the `ws` fixture registers a recording socket (`ws.types`,
  `ws.of_type(...)`); the handshake is tested with Starlette's `TestClient`.
- **Exactly one uvicorn worker** — the socket set is in-process memory.
- FCM: data-only messages, all values strings; skip when any WS client is
  connected or the chat is muted; delete UNREGISTERED tokens.
- Blocking SDKs (firebase-admin, boto3) only via `asyncio.to_thread`.

## Config

- All settings live in `config/app_config.py` (`AppConfig`); secrets are
  `SecretStr`. Alembic uses `DatabaseConfig`, seed uses `SeedConfig` — these
  must stay import-safe (no side effects).
- New env var -> add it to the right config class **and** `.env.example`.
- `.env`: comments on their own line, never after a value.
- Secrets never go in the DB, code, or git (`secrets/` and `.env` are ignored).

## Tests

- `make test`. Tests run against `<POSTGRES_DB>_test` (auto-created,
  migrated and seeded by `tests/conftest.py`) — never the dev database.
- Use the fixtures: `client` (httpx ASGI), `auth_headers`, `operator`,
  `business`, `sent_codes` (captures OTPs instead of sending),
  `dev_static_otp`, `meta` (autouse `FakeMeta` — records sends, set
  `.error` to fail them; tests never hit the real Graph API).
  `DEV_STATIC_OTP` is forced OFF unless a test asks for it.
- Row builders and shared asserts live in `tests/factories.py`
  (`make_chat`, `make_open_chat`, `make_messages`, `assert_error`, ...).
- The ASGI test client does NOT run the lifespan: anything created there
  (`app.state.meta`) is reached through a dependency tests can override.
- BackgroundTasks finish before the ASGI test client returns, so a test can
  assert the post-send state right after the POST.
- Tables a test writes to must be listed in `_MUTABLE_TABLES` in conftest so
  they are truncated between tests.
- Assert the envelope (`{"data","meta"}` / `{"errors"}`) and exact key sets
  of contract shapes, not just status codes.

## Logging & security

- structlog, snake_case event names: `logger.info("message_sent", chat_id=...)`.
- **Never log**: `META_ACCESS_TOKEN`, `JWT_SECRET`, OTP codes, message bodies,
  the WS `?token=` query (a filter redacts it — don't bypass it), phone
  numbers in full where avoidable.
- Validate at the edges (Pydantic schemas); trust internal calls.

## Don't

- Don't add `HTTPException`, relative imports, or `src.`-prefixed imports.
- Don't return raw dicts/models from JSON routes — always `ApiResponse`.
- Don't put SQL in services/routers or business rules in repositories.
- Don't register routers anywhere but `routes.py`.
- Don't run more than one worker.
- Don't rename JSON keys the Flutter client parses.
