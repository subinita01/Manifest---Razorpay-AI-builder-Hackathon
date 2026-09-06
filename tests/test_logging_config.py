import json
import logging

from backend.logging_config import JSONFormatter, configure_logging


def test_json_formatter_produces_valid_json_with_expected_fields():
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="manifest.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    parsed = json.loads(formatter.format(record))
    assert parsed["message"] == "hello world"
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "manifest.test"
    assert "timestamp" in parsed
    assert "correlation_id" not in parsed


def test_json_formatter_includes_correlation_id_when_present():
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="manifest.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="uh oh",
        args=(),
        exc_info=None,
    )
    record.correlation_id = "abc123"
    parsed = json.loads(formatter.format(record))
    assert parsed["correlation_id"] == "abc123"


def test_json_formatter_includes_exception_traceback():
    formatter = JSONFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord(
            name="manifest.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failed",
            args=(),
            exc_info=sys.exc_info(),
        )
    parsed = json.loads(formatter.format(record))
    assert "ValueError: boom" in parsed["exception"]


def test_configure_logging_sets_a_single_json_handler(monkeypatch):
    monkeypatch.setenv("MANIFEST_LOG_JSON", "true")
    monkeypatch.setenv("MANIFEST_LOG_LEVEL", "DEBUG")
    configure_logging()
    logger = logging.getLogger("manifest")
    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0].formatter, JSONFormatter)
    assert logger.level == logging.DEBUG
    assert logger.propagate is False


def test_configure_logging_can_use_plain_text_instead(monkeypatch):
    monkeypatch.setenv("MANIFEST_LOG_JSON", "false")
    configure_logging()
    logger = logging.getLogger("manifest")
    assert not isinstance(logger.handlers[0].formatter, JSONFormatter)
