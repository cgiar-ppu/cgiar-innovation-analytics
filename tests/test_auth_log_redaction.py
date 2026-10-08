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


def _capture(logger_name, msg, *args):
    import io

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(name)s %(message)s"))
    logger = logging.getLogger(logger_name)
    old_level, old_prop = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        logger.info(msg, *args)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        logger.propagate = old_prop
    return stream.getvalue()


def test_every_logger_is_redacted_not_only_the_uvicorn_ones():
    """INT-3b note 1 (defensive): the app's own loggers and child loggers too."""
    install_auth_url_redaction()
    for name in ("synapsis_agent", "uvicorn.access.child", "some.library"):
        out = _capture(name, "GET %s", "/ws/chat?token=eyJsynthetic.private.jwt&x=1")
        assert "eyJsynthetic" not in out and "token=[REDACTED]&x=1" in out, out
    out = _capture("synapsis_agent", "export link /api/files/a.docx?token=private-token")
    assert "private-token" not in out


def test_uvicorn_access_log_line_is_redacted_after_its_logging_config():
    """uvicorn.run() applies its dictConfig AFTER the app is imported."""
    import logging.config

    from uvicorn.config import LOGGING_CONFIG

    install_auth_url_redaction()
    logging.config.dictConfig(LOGGING_CONFIG)
    out = _capture("uvicorn.access", '%s - "%s %s HTTP/%s" %d',
                   "10.0.0.1:5000", "GET", "/api/export/x?format=pdf&token=private-token", "1.1", 200)
    assert "private-token" not in out and "token=[REDACTED]" in out


def test_record_factory_installation_is_idempotent():
    install_auth_url_redaction()
    first = logging.getLogRecordFactory()
    install_auth_url_redaction()
    assert logging.getLogRecordFactory() is first
