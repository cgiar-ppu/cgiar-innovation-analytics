import logging

from synapsis.auth.log_redaction import AuthUrlFilter, install_auth_url_redaction


def test_websocket_handshake_logging_redacts_query_credentials():
    record = logging.LogRecord("uvicorn.error", logging.INFO, "test", 1,
        '%s - "WebSocket %s" [accepted]', ("client", "/ws/chat?token=synthetic-private-token&mode=chat"), None)
    AuthUrlFilter().filter(record)
    rendered = record.getMessage()
    assert "synthetic-private-token" not in rendered
    assert "token=[REDACTED]&mode=chat" in rendered


def test_callback_and_named_arguments_are_redacted():
    record = logging.LogRecord("httpx", logging.INFO, "test", 1,
        "GET https://app/auth/callback?code=private-code&state=private-state", (), None)
    AuthUrlFilter().filter(record)
    assert "private-code" not in record.getMessage() and "private-state" not in record.getMessage()
    record = logging.LogRecord("uvicorn.access", logging.INFO, "test", 1,
        "%(path)s", ({"path": "/api/export?token=private-token"},), None)
    AuthUrlFilter().filter(record)
    assert record.getMessage() == "/api/export?token=[REDACTED]"


def test_filter_installation_is_idempotent():
    install_auth_url_redaction()
    install_auth_url_redaction()
    for name in ("uvicorn.error", "uvicorn.access", "httpx"):
        assert sum(isinstance(f, AuthUrlFilter) for f in logging.getLogger(name).filters) == 1
