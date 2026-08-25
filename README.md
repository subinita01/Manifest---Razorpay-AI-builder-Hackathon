# MANIFEST

MANIFEST is a deterministic reconciliation and exception auditor for settlement, bank, and ledger data, built for the Razorpay AI Buildathon Track 04.

## Goal

This project reconstructs the gross-to-net settlement bridge, validates TDS migration rules, and emits an explicit exception manifest rather than silently absorbing variance.

## Repository shape

- `app/` — Streamlit demo experience
- `backend/` — FastAPI service and reconciliation logic
- `core/` — deterministic matching engine and schema contracts
- `config/` — YAML and environment configuration
- `data/` — synthetic datasets and generated fixtures
- `scripts/` — generation and evaluation helpers
- `tests/` — regression and contract tests

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

## Core principles

- `Decimal` for all monetary math
- deterministic matching cascade with explicit exceptions
- `--no-llm` mode must still run successfully
- audit trail is append-only and hash-chained
- no silent match clearing

## Demo narrative

The product focuses on the FY 2026-27 TDS code migration break, where legacy section codes like 194J and 194C shift to numeric payment codes. The matching engine treats that as a first-class exception class instead of burying it in `UNEXPLAINED`.

## Critical note

The legacy-to-numeric code mapping in `config/tds_code_map.yaml` is intentionally config-driven and swappable so the tax schedule can be updated without refactoring the engine.
