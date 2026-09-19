"""Build a SIGNED sample Meta webhook body for manual testing (api.rest).

    make webhook-sample                                   # status "delivered"
    make webhook-sample status=read wamid=wamid.HBgM...
    make webhook-sample kind=message from=919820011223 text="Hi" name="Ananya"
    make webhook-send kind=message text="Hi"      # build + sign + POST it

Writes .webhook/body.json (gitignored) and prints the X-Hub-Signature-256
value to paste into api.rest. The body is signed byte-for-byte, so don't
edit the file after generating it.
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

from config.seed_config import SeedConfig
from modules.webhook.signature import compute_signature

OUT = Path(".webhook") / "body.json"


def build(args: argparse.Namespace, phone_number_id: str) -> tuple[dict, str]:
    now = str(int(time.time()))
    wamid = args.wamid or f"wamid.TEST{uuid.uuid4().hex[:24].upper()}"
    value: dict = {
        "messaging_product": "whatsapp",
        "metadata": {
            "display_phone_number": "0000000000",
            "phone_number_id": phone_number_id,
        },
    }
    if args.kind == "message":
        value["contacts"] = [{"profile": {"name": args.name}, "wa_id": args.sender}]
        value["messages"] = [
            {
                "from": args.sender,
                "id": wamid,
                "timestamp": now,
                "type": "text",
                "text": {"body": args.text},
            }
        ]
    else:
        status: dict = {
            "id": wamid,
            "status": args.status,
            "timestamp": now,
            "recipient_id": args.sender,
        }
        if args.status == "failed":
            status["errors"] = [{"code": 131026, "title": "Message undeliverable"}]
        value["statuses"] = [status]

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {"id": "0", "changes": [{"field": "messages", "value": value}]},
        ],
    }
    return payload, wamid


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["status", "message"], default="status")
    parser.add_argument(
        "--status",
        choices=["sent", "delivered", "read", "failed"],
        default="delivered",
    )
    parser.add_argument("--wamid", default="")
    parser.add_argument("--from", dest="sender", default="919820011223")
    parser.add_argument("--text", default="Hello from the webhook sample")
    parser.add_argument("--name", default="Test Customer")
    # base URL: also POST the signed body there (no copy-paste of signatures)
    parser.add_argument("--send", default="")
    # make passes empty strings for unset vars
    args = parser.parse_args([a for a in sys.argv[1:] if not a.endswith("=")])

    payload, wamid = build(args, SeedConfig().business_phone_number_id)
    body = json.dumps(payload, separators=(",", ":")).encode()

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_bytes(body)

    signature = compute_signature(body)
    print(f"wrote     {OUT}")  # noqa: T201
    print(f"kind      {args.kind}  wamid={wamid}")  # noqa: T201
    print(f"signature {signature}")  # noqa: T201

    if args.send:
        url = f"{args.send.rstrip('/')}/webhook"
        resp = httpx.post(
            url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature,
            },
            timeout=15,
        )
        print(f"sent      POST {url} -> {resp.status_code} {resp.text}")  # noqa: T201
        return 0 if resp.status_code == 200 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
