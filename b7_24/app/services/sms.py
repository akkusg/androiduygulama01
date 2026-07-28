from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from werkzeug.exceptions import ServiceUnavailable


def send_otp_sms(config, phone: str, code: str) -> None:
    provider = config["SMS_PROVIDER"].lower()
    message = f"Yedi Yirmi Dort dogrulama kodunuz: {code}"

    if provider == "console":
        config.get("LOGGER", logging.getLogger(__name__)).info(
            "Development OTP for %s: %s", phone, code
        )
        return
    if provider == "static":
        return
    if provider == "twilio":
        _send_twilio_sms(config, phone, message)
        return
    raise ServiceUnavailable("SMS provider is not configured")


def _send_twilio_sms(config, phone: str, message: str) -> None:
    account_sid = config.get("TWILIO_ACCOUNT_SID", "")
    auth_token = config.get("TWILIO_AUTH_TOKEN", "")
    from_number = config.get("TWILIO_FROM_NUMBER", "")
    if not account_sid or not auth_token or not from_number:
        raise ServiceUnavailable("Twilio credentials are not configured")

    url = (
        "https://api.twilio.com/2010-04-01/Accounts/"
        f"{urllib.parse.quote(account_sid, safe='')}/Messages.json"
    )
    body = urllib.parse.urlencode(
        {"To": phone, "From": from_number, "Body": message}
    ).encode("utf-8")
    credentials = base64.b64encode(
        f"{account_sid}:{auth_token}".encode("utf-8")
    ).decode("ascii")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    try:
        # The request host and HTTPS scheme are fixed above.
        with urllib.request.urlopen(  # nosec B310
            request,
            timeout=10,
        ) as response:
            if response.status < 200 or response.status >= 300:
                raise ServiceUnavailable("SMS provider rejected the request")
    except urllib.error.HTTPError as error:
        detail = _twilio_error_message(error)
        raise ServiceUnavailable(detail) from error
    except urllib.error.URLError as error:
        raise ServiceUnavailable("SMS provider is unavailable") from error


def _twilio_error_message(error: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(error.read().decode("utf-8"))
        provider_message = payload.get("message")
    except (UnicodeDecodeError, json.JSONDecodeError):
        provider_message = None
    return provider_message or "SMS provider rejected the request"
