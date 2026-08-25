import json
from pathlib import Path

from core.audit import AuditLogger


def test_empty_or_missing_log_is_valid(tmp_path: Path):
    logger = AuditLogger(tmp_path / "audit.jsonl")
    assert logger.verify_chain() is True


def test_chain_of_appends_is_valid(tmp_path: Path):
    logger = AuditLogger(tmp_path / "audit.jsonl")
    logger.append({"event": "a"})
    logger.append({"event": "b"})
    logger.append({"event": "c"})
    assert logger.verify_chain() is True


def test_mutating_a_record_breaks_the_chain(tmp_path: Path):
    log_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_path)
    logger.append({"event": "a"})
    logger.append({"event": "b"})
    logger.append({"event": "c"})
    assert logger.verify_chain() is True

    lines = log_path.read_text().splitlines()
    tampered = json.loads(lines[1])
    tampered["event"] = {"event": "TAMPERED"}
    lines[1] = json.dumps(tampered, sort_keys=True)
    log_path.write_text("\n".join(lines) + "\n")

    assert logger.verify_chain() is False


def test_reordering_records_breaks_the_chain(tmp_path: Path):
    log_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_path)
    logger.append({"event": "a"})
    logger.append({"event": "b"})

    lines = log_path.read_text().splitlines()
    log_path.write_text("\n".join(reversed(lines)) + "\n")

    assert logger.verify_chain() is False
