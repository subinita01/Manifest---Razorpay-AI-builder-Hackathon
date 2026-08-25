#!/usr/bin/env bash
# Freezes the demo to a known-good state before a live run:
#   1. Restore data/demo/ from git (undoes any accidental edits or
#      regeneration drift since the committed fixtures).
#   2. Clear the DuckDB file and audit log, so the demo starts from a
#      genuinely empty run history -- no stale idempotency cache making
#      the first "Run reconciliation" click suspiciously instant.
#   3. Pre-warm Python: import the heavy modules (pydantic core schema
#      builds, rapidfuzz, duckdb, streamlit) and run the deterministic
#      cascade once directly (core.pipeline.run_pipeline, NOT through
#      reconcile()/DuckDB) so import and first-JIT-like costs are paid
#      here, not on the presenter's first live click -- without seeding
#      the demo run's own cache entry, so that click still visibly
#      computes rather than returning an instant cache hit.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Restoring data/demo/ from git"
git checkout -- data/demo/

echo "==> Clearing DuckDB and audit log"
rm -f data/manifest.duckdb data/manifest.duckdb.wal data/audit.jsonl

echo "==> Pre-warming imports and running the cascade once (not cached)"
.venv/bin/python -c "
import time
start = time.monotonic()

from pathlib import Path
from core.ingest import load_bank_csv, load_ledger_csv, load_settlement_csv
from core.pipeline import run_pipeline
import duckdb, streamlit, rapidfuzz  # noqa: F401

demo = Path('data/demo')
bank = load_bank_csv(demo / 'bank_statement.csv')
settlement = load_settlement_csv(demo / 'settlement_batch.csv')
ledger = load_ledger_csv(demo / 'internal_ledger.csv')
result = run_pipeline(bank, settlement, ledger, fuzzy_auto_match_threshold=0.90)

elapsed = time.monotonic() - start
print(f'Pre-warm run: total={result.total_input_rows} matched={result.matched_row_count} '
      f'exceptions={result.exception_row_count} ({elapsed:.2f}s)')
"

echo "==> Demo reset complete. Run: make demo"
