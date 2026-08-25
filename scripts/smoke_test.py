"""CI smoke test: runs the real reconciliation pipeline (ingest, matching
cascade, DuckDB persistence, and the audit chain) against the committed
demo dataset with use_llm=False, and asserts the core invariant --
matched + needs_review + exceptions == total_input_rows -- holds. Exits
non-zero on any failure so CI fails loudly, not silently.

Runs against a throwaway DB and audit log in a temp directory, same as
the test suite's isolation (tests/conftest.py), so it never touches
data/manifest.duckdb or data/audit.jsonl.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import backend.audit_log as audit_log
import backend.db as db_module
from backend.db import get_connection, get_run
from backend.services.reconcile_service import reconcile


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_module.DEFAULT_DB_PATH = tmp_path / "smoke.duckdb"
        audit_log.AUDIT_LOG_PATH = tmp_path / "smoke_audit.jsonl"

        conn = get_connection()
        run_id = reconcile(conn, dataset_id="demo", use_llm=False, fuzzy_threshold=0.90)
        stored = get_run(conn, run_id)

        accounted = (
            stored["matched_row_count"]
            + stored["needs_review_row_count"]
            + stored["exception_row_count"]
        )
        if accounted != stored["total_input_rows"]:
            print(
                f"INVARIANT VIOLATED: matched({stored['matched_row_count']}) + "
                f"needs_review({stored['needs_review_row_count']}) + "
                f"exceptions({stored['exception_row_count']}) = {accounted}, "
                f"expected total_input_rows={stored['total_input_rows']}",
                file=sys.stderr,
            )
            return 1

        chain_valid = audit_log.get_audit_logger().verify_chain()
        if not chain_valid:
            print("AUDIT CHAIN INVALID immediately after a fresh run", file=sys.stderr)
            return 1

        print(
            f"Smoke test OK: run_id={run_id} total_input_rows={stored['total_input_rows']} "
            f"matched={stored['matched_row_count']} "
            f"needs_review={stored['needs_review_row_count']} "
            f"exceptions={stored['exception_row_count']} audit_chain_valid={chain_valid}"
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
