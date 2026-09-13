"""Redact credential-bearing URLs, including Uvicorn's WebSocket error logger."""
import logging
import re

_CREDENTIAL_QUERY = re.compile(
    r'([?&](?:token|code|access_token|id_token|refresh_token|client_secret|invite|state)=)[^&\s"\']+',
    re.IGNORECASE,
)


def redact(value):
    return _CREDENTIAL_QUERY.sub(r'\1[REDACTED]', value) if isinstance(value, str) else value


class AuthUrlFilter(logging.Filter):
    def filter(self, record):
        record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: redact(value) for key, value in record.args.items()}
        return True


def install_auth_url_redaction():
    for name in ("uvicorn.error", "uvicorn.access", "httpx"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, AuthUrlFilter) for f in logger.filters):
            logger.addFilter(AuthUrlFilter())
