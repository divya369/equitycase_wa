import httpx
import pytest
from pydantic import SecretStr

from config.app_config import app_config
from integrations.sms.sender import (
    NullOtpSender,
    SmsDeliveryError,
    SmsForYouSender,
    get_otp_sender,
)

API_URL = "https://sms.example.test/api"


def make_sender(handler) -> tuple[SmsForYouSender, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    sender = SmsForYouSender(
        api_url=API_URL,
        api_key="KEY123",
        sender_id="EQCASE",
        transport=httpx.MockTransport(record),
    )
    return sender, seen


async def test_sends_dlt_template_with_country_code():
    sender, seen = make_sender(lambda r: httpx.Response(200, json={"status": "OK"}))
    await sender.send_otp(phone="+91 87991 90997", code="482913")

    assert len(seen) == 1
    request = seen[0]
    assert request.method == "GET"
    assert str(request.url).startswith(API_URL + "?")
    assert dict(request.url.params) == {
        "apikey": "KEY123",
        "senderid": "EQCASE",
        "number": "918799190997",
        "message": (
            "482913 is your otp to verify your mobile number. Please do not "
            "share it with anyone for security reason. Anand Money Changers "
            "Mo: 7400874009"
        ),
        "format": "json",
    }


@pytest.mark.parametrize("status", [400, 401, 500, 503])
async def test_gateway_error_raises(status):
    sender, seen = make_sender(lambda r: httpx.Response(status))
    with pytest.raises(SmsDeliveryError):
        await sender.send_otp(phone="+918799190997", code="111111")
    # never retried — a retry could deliver two codes
    assert len(seen) == 1


async def test_unreachable_gateway_raises():
    def fail(request):
        raise httpx.ConnectError("down", request=request)

    sender, _ = make_sender(fail)
    with pytest.raises(SmsDeliveryError):
        await sender.send_otp(phone="+918799190997", code="111111")


def test_factory_uses_sms_when_configured(monkeypatch):
    monkeypatch.setattr(app_config, "sms_api_url", API_URL)
    monkeypatch.setattr(app_config, "sms_api_key", SecretStr("KEY123"))
    monkeypatch.setattr(app_config, "sender_id", "EQCASE")
    assert isinstance(get_otp_sender(), SmsForYouSender)


@pytest.mark.parametrize("missing", ["sms_api_url", "sms_api_key", "sender_id"])
def test_factory_falls_back_when_incomplete(monkeypatch, missing):
    monkeypatch.setattr(app_config, "sms_api_url", API_URL)
    monkeypatch.setattr(app_config, "sms_api_key", SecretStr("KEY123"))
    monkeypatch.setattr(app_config, "sender_id", "EQCASE")
    monkeypatch.setattr(app_config, missing, None)
    assert isinstance(get_otp_sender(), NullOtpSender)


async def test_failed_sms_is_502(client, operator, monkeypatch):
    class Failing:
        async def send_otp(self, *, phone, code):
            raise SmsDeliveryError("down")

    monkeypatch.setattr("modules.auth.dependencies.get_otp_sender", lambda: Failing())
    resp = await client.post("/v1/auth/otp/request", json={"phone": operator.phone})
    assert resp.status_code == 502
    assert resp.json()["errors"]["code"] == "bad_gateway"
