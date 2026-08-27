# MANIFEST

[![CI](https://github.com/subinita01/Manifest---Razorpay-AI-builder-Hackathon/actions/workflows/ci.yml/badge.svg)](https://github.com/subinita01/Manifest---Razorpay-AI-builder-Hackathon/actions/workflows/ci.yml)

**Live demo:** [manifest---razorpay-ai-builder-hackathongit-gqvpypgmk6jyx9fq3a.streamlit.app](https://manifest---razorpay-ai-builder-hackathongit-gqvpypgmk6jyx9fq3a.streamlit.app/) -- no install required, the demo dataset loads with one click.

MANIFEST is a settlement, tax-line, and exception auditor for Razorpay-style payment reconciliation, built for the Razorpay AI Buildathon Track 04.

**It tells you what it couldn't match.**

A reconciliation tool that reports 100% match is lying to you or hiding the mess in a bucket nobody reads. MANIFEST runs a deterministic 6-stage matching cascade over your bank statement, settlement batch, and internal ledger, reconstructs the gross-to-net settlement bridge, validates the incoming TDS code migration, and emits an honest, taxonomy-coded exception list for everything it couldn't resolve on its own -- with an append-only, hash-chained audit trail behind every decision.

## Headline numbers

From `make eval`, against the committed demo dataset (seed 42, 600 orders, 1,273 total rows across all three inputs) -- full detail in [evaluation/results/ablation.md](evaluation/results/ablation.md) and [threshold_sweep.md](evaluation/results/threshold_sweep.md):

| Metric | Value |
|---|---|
| Auto-match rate | 62.9% |
| Matcher precision | 1.000 |
| Matcher recall | 0.733 |
| False-positive cost | Rs 0.00 |
| Total exceptions raised | 45 (covering 269 of 1,273 rows) |
| UNEXPLAINED (system refused to guess) | 3 |
| Core invariant (matched + needs_review + exceptions == total) | holds |

The LLM-advisory row in the same table reports **zero uplift on every core metric, by design** -- see [Architecture: the LLM contract](ARCHITECTURE.md#the-llm-contract) for why that's a guarantee, not a shortfall.

## Architecture

```mermaid
flowchart TD
    subgraph Input["Three CSV inputs"]
        A[bank_statement.csv]
        B[settlement_batch.csv]
        C[internal_ledger.csv]
    end

    A --> D["core/ingest.py"]
    B --> D
    C --> D
    D --> E["core/pipeline.run_pipeline"]

    subgraph Cascade["Deterministic cascade -- core/ (never imports llm/)"]
        E --> S1["Stage 1: UTR exact match"]
        S1 --> S2["Stage 2: gross-to-net bridge"]
        S2 --> S3["Stage 3: settlement-to-ledger order match"]
        S3 --> S4["Stage 4: TDS code-migration validation"]
        S4 --> S5["Stage 5: fuzzy match on Stage 1's residue"]
        S5 --> S6["Stage 6: exception classification"]
    end

    S6 --> R["RunResult: matched / needs_review / exceptions"]
    R --> AU["core/audit.py: hash-chained decision log"]
    R -. "use_llm=True, advisory only" .-> L["llm/enrich.py"]
    L -. "detail dict only -- never reclassifies" .-> R
    R --> DB[("DuckDB -- backend/db.py")]
    DB --> API["FastAPI -- backend/routes.py"]
    DB --> UI["Streamlit -- app/streamlit_app.py"]
```

Full design rationale, the LLM guardrails, and the known scaling limit: [ARCHITECTURE.md](ARCHITECTURE.md).

## Quickstart

```bash
make install     # creates .venv, installs requirements.txt
make demo-data   # generates data/demo/ (seed 42, 600 orders) -- already committed, but reproducible
make eval        # writes evaluation/results/ablation.md and threshold_sweep.md
make demo        # streamlit run app/streamlit_app.py
```

Four commands, no API key required -- `use_llm` defaults to off, and even switched on with no key set, the app runs end to end against the deterministic `NullAdapter` fallback. Want to see the live LLM path without a paid key? `build_adapter_from_env` checks `ANTHROPIC_API_KEY` first, then `GEMINI_API_KEY` (free tier at [aistudio.google.com](https://aistudio.google.com/apikey) -- caps at 20 requests/day/model, easy to exhaust), then `NVIDIA_API_KEY` (a DeepSeek model via [build.nvidia.com](https://build.nvidia.com) -- correct, but noticeably slower per call than the other two).

## Try the upload flow with your own CSVs

The Upload tab's "Load demo dataset" button is one click, but the app also accepts arbitrary bank/settlement/ledger CSVs through its own upload form -- to actually exercise that path rather than just the pre-loaded demo, [data/sample_upload/](data/sample_upload/) has a second, independently generated dataset (seed 7, different from the seed-42 demo) ready to upload: `bank_statement.csv`, `settlement_batch.csv`, `internal_ledger.csv`. Pick those three in the Upload tab, click "Validate and use these files," then Run -- it produces a genuinely different result (1,057 matched / 9 needs review / 207 exceptions, vs. the demo's 1,001 / 3 / 269), proving the run reflects whatever you actually uploaded. `ground_truth.json` is included alongside it for anyone who wants to verify MANIFEST's output independently, same as the main demo dataset -- it isn't one of the three files you upload.

## What this deliberately does NOT do

- No real bank or Razorpay API integration -- CSV in, CSV/DuckDB out.
- No multi-tenant auth, user accounts, or RBAC.
- Never posts an entry to any accounting system -- adjustment drafts are drafts, always.
- No PDF/OCR invoice parsing, no multi-currency or cross-border handling, nothing real-time or streaming, no GST return filing.
- **It does not claim 100% match.** A run reporting zero exceptions is a failed run, and the UI says so.
- **The LLM never clears a match, and never can.** It explains and drafts. Deterministic code in `core/` decides, and `core/` has no import path to `llm/` at all.

## Security

Full threat model and mitigating controls: [SECURITY.md](SECURITY.md). The one line that matters for a panel: bank narration text is wrapped in an `<untrusted_data>` tag before it ever reaches the LLM, and a deterministic keyword scan flags suspicious narration *before* any adapter is consulted -- so even an adversarial LLM response that claims an injected row is "a clean, high-confidence match" cannot change the match outcome. Proven in `tests/test_prompt_injection.py` against an adapter built to try exactly that.

## A known gap, on purpose

`config/tds_code_map.yaml` -- the legacy-section-to-new-numeric-code mapping for the FY 2026-27 TDS migration -- ships with every entry marked `verified: false`. These are placeholder values pending confirmation against the official CBDT notification; the file is the single source of truth precisely so that correcting them later requires editing YAML, not refactoring `core/`. MANIFEST treats an unverified or contradicted mapping as a first-class `TDS_CODE_MIGRATION_BREAK` exception rather than silently trusting it.

## Repository shape

- `app/` -- Streamlit demo (Upload, Run, Bridge, Manifest, Metrics tabs)
- `backend/` -- FastAPI service, DuckDB persistence, security controls, audit wiring
- `core/` -- the deterministic matching cascade and schema contracts (`llm/`-free, 95%+ test coverage)
- `llm/` -- optional advisory layer (narration classification, root-cause narrative, adjustment drafts, and an on-demand natural-language Q&A over a run's exceptions)
- `config/` -- YAML configuration (TDS code map, tolerances, chart of accounts)
- `data/` -- synthetic generator, the committed demo dataset (seed 42) with ground truth, and a second sample dataset (seed 7) for testing the manual upload flow
- `evaluation/` -- metrics, ablation, and threshold-sweep scoring against ground truth
- `scripts/` -- CI smoke test and demo utilities
- `tests/` -- unit, integration, and security regression tests
