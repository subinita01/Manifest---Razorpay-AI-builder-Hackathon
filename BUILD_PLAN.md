# Build plan

## Phase 1 — Foundation
- Set up the project scaffold and package layout
- Add configuration and data contracts
- Add base README, architecture, and security notes

## Phase 2 — Deterministic data contracts
- Model bank, settlement, and ledger inputs
- Add config-driven TDS code map
- Create synthetic dataset generator skeleton

## Phase 3 — Matching engine
- Stage 0: normalize input records
- Stage 1: exact UTR matching
- Stage 2: gross-to-net bridge reconciliation
- Stage 3+: order match, TDS validation, fuzzy match, and exception classification

## Phase 4 — API + UI
- Expose `/healthz`, `/ingest`, `/reconcile`, and metrics endpoints
- Wire the Streamlit tabs to the API and local demo states

## Phase 5 — Evaluation and audit
- Add ground-truth evaluator and ablation metrics
- Implement append-only audit log and hash chaining
- Ensure `--no-llm` always remains valid

## Phase 6 — Demo polish
- Short, clear narrative for the panel
- Reproducible runbook and architecture one-pager
- Honest `UNEXPLAINED` reporting as a feature, not a bug
