"""Conservative structured-key/common-pattern redaction, not secret detection."""

import json
import re

_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "access_token",
}
_PATTERN = re.compile(r"(?i)\b(password|passwd|secret|token|api_key|apikey)\s*[=:]\s*[^\s,;\"']+")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


def redact(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        # Tool arguments and tool outputs are JSON encoded inside event payloads.
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            decoded = None
        if isinstance(decoded, (dict, list)):
            return json.dumps(redact(decoded), sort_keys=True)
        return _BEARER.sub("Bearer [REDACTED]", _PATTERN.sub(r"\1=[REDACTED]", value))
    return value


def redact_object(payload: dict[str, object]) -> dict[str, object]:
    return {
        key: "[REDACTED]" if key.lower() in _KEYS else redact(value)
        for key, value in payload.items()
    }
