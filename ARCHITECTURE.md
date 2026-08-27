# Architecture

## The cascade

Every reconciliation run passes three CSVs (`bank_statement`, `settlement_batch`, `internal_ledger`) through six stages, in a fixed order, inside `core/pipeline.run_pipeline`. Each stage only ever operates on what the previous stage left unresolved -- nothing is re-examined twice, and nothing downstream can override an upstream decision.

1. **Stage 1 -- UTR exact match** (`core/matching/stage1_utr.py`). A bank credit and a settlement batch match only if the UTR is exact (case-insensitive), the net amount agrees within `TOLERANCE` (Rs 0.01), and the dates agree within 2 days. If more than one bank row claims the same UTR, none of them are matched -- the tie is emitted as `AMBIGUOUS_MATCH` rather than broken arbitrarily.

2. **Stage 2 -- gross-to-net bridge** (`core/matching/stage2_bridge.py`). For every UTR-group Stage 1 (or Stage 5) matched, reconstructs `Gross - MDR - GST + Refunds + Chargebacks - On-Hold = expected_net` from the settlement's own recorded figures and compares it to the bank credit. This runs two independent checks: does the settlement's own bookkeeping actually add up (`closed` / `residual` / attribution), and separately, does the *recorded* fee/GST rate match the *contracted* rate regardless of whether the bridge closes (`rate_variance`) -- a batch can reconcile perfectly to the bank while still being charged the wrong rate, and that's a compliance finding, not a bookkeeping error.

3. **Stage 3 -- settlement-to-ledger order match** (`core/matching/stage3_order.py`). Matches settlement payment rows to internal ledger rows on `order_id`. What's left over becomes `SETTLEMENT_ONLY` (no ledger record) or `LEDGER_ONLY` (no settlement record) residue for Stage 6.

4. **Stage 4 -- TDS code-migration validation** (`core/matching/stage4_tds.py`). Runs against every order Stage 3 matched that carries TDS. A fixed rule order fires at most one finding per order: migration break (legacy section present, new code missing, posted on/after cutover) → code contradiction (both codes present but disagree) → amount deviation (recomputed TDS vs. recorded, checked *before* rate deviation, deliberately reversing the naive order -- a fixed rupee-level posting slip produces an outsized *relative* rate deviation on a small order even when nothing about the rate itself is wrong) → rate deviation.

5. **Stage 5 -- fuzzy match on residue** (`core/matching/stage5_fuzzy.py`). Runs only over what Stage 1 couldn't resolve. Score = 0.5·amount + 0.2·date + 0.3·narration (rapidfuzz `token_set_ratio` against the UTR, catching a truncated reference that still shares digits with the true one). Above `auto_match_threshold`: matched. Between that and `needs_review_threshold`: a proposal, never promoted automatically. Below: left unresolved. Exactly like Stage 1, a near-tie between the top two candidates (within `ambiguity_margin`) is never broken arbitrarily -- it's emitted as `AMBIGUOUS_MATCH`.

6. **Stage 6 -- exception classification** (`core/matching/stage6_classify.py`). Does no new detection of its own -- it only assigns a taxonomy code to whatever attribution the earlier stages already recorded. Anything with no attribution becomes `UNEXPLAINED`, which is a legitimate terminal state, never a forced guess.

Every stage's contribution is reconciled by `core/pipeline.py` against one invariant: `matched_row_count + needs_review_row_count + exception_row_count == total_input_rows`. If that ever fails to hold, the pipeline raises `InvariantViolation` rather than returning a plausible-looking but wrong summary.

## Why deterministic-first

The matching decision that determines whether money is accounted for correctly has to be reproducible, testable with fixed inputs and expected outputs, and auditable by a human reading code -- not a model's weights. Every one of the six stages above is plain Python control flow over typed dicts, with no model call anywhere in the decision path. `core/` (the entire cascade, the bridge, the taxonomy, the audit chain, the Pydantic contracts) has **zero import of `llm/`** -- not "the LLM is turned off by default," but structurally incapable of being consulted, which `tests/test_prompt_injection.py` proves by running the full pipeline with no `llm` import ever executed and getting a byte-identical result to a run where an adversarial adapter was available and consulted.

This is also why the product's central claim is "it tells you what it couldn't match," not "it matches everything": a deterministic system that can't explain a row says so (`UNEXPLAINED`, `AMBIGUOUS_MATCH`) instead of quietly forcing a plausible-sounding answer. A run reporting zero exceptions is treated as a *failed* run.

## The LLM contract

`llm/` is strictly advisory and additive. `llm/enrich.enrich_run_result` is the only place a `RunResult` and an LLM adapter meet, and it can only ever write three new keys into an `Exception_.detail` dict (`llm_narration_classification`, `llm_root_cause`, `llm_adjustment_draft`) -- it cannot touch `taxonomy_code`, `row_ids`, `amount_impact`, or the matched/needs_review lists, and it runs *after* the cascade has already finished and persisted its own decision.

A fourth job, `llm/query.answer_question`, is separate from that eager per-run enrichment: it's an on-demand natural-language Q&A over an already-completed run's exceptions, driven live from the Manifest tab's "Ask about this run" box. It's advisory in the same structural sense as the other three -- it only ever returns text for display, it's never called from `core/pipeline.py` or `llm/enrich.py`, and it has no write path into `RunResult`, an exception, or anything persisted, so there's no mechanism by which an answer -- wrong, hallucinated, or otherwise -- could alter a decision. Any exception ID it cites is checked against the run's real exception IDs before being shown; a cited ID the model invented is dropped rather than making the whole answer untrustworthy.

Guardrails, each backed by a test:

- **Deterministic short-circuit before the model is even consulted.** `llm/advisory.classify_narration` scans bank narration against a fixed set of suspicious patterns (`_SUSPICIOUS_PATTERNS`) and flags it directly if matched -- an adapter is never asked to judge a payload that already looks like an injection attempt.
- **Untrusted-data wrapping.** Every prompt (`llm/prompts.py`) wraps external text (narration, exception detail) in an explicit `<untrusted_data>` tag with instructions that its contents are data, never instructions.
- **Field pruning.** `prune_fields` caps what's sent to the model at `MAX_PRUNED_FIELDS=12`, and `root_cause_prompt` refuses to run against an unpruned payload.
- **Zero temperature, capped retries.** `AnthropicAdapter` runs at `temperature=0` with `MAX_RETRIES=1` -- advisory text should be as reproducible as the budget allows, not creative.
- **Hallucination guard on drafts.** `generate_adjustment_draft` validates every account name the model proposes against `config/chart_of_accounts.yaml` and falls back to a safe default if the model invents one that doesn't exist.
- **Adversarial-adapter test.** `tests/test_prompt_injection.py` runs the pipeline against an adapter built to claim an injected row is "a clean, high-confidence match" and asserts the match/exception outcome is identical whether or not that adapter runs at all.

With no `ANTHROPIC_API_KEY` set, `build_adapter` returns `NullAdapter`, which always returns `None` -- the app runs end to end, `use_llm=True` included, with every advisory field simply absent. The demo dataset's ablation table (`evaluation/results/ablation.md`) reports the LLM-advisory row's uplift on every core metric as **exactly zero**, and states that plainly rather than omitting the row or padding it -- by this contract, it always will be zero, however the row is regenerated, because the LLM layer has no path to change which stage matched what.

## Known scaling limit

The current implementation loads all three input CSVs fully into memory as plain Python `list[dict]` structures (`core/ingest.py`, via `csv.DictReader`) and every stage of the cascade is pure Python over those in-memory structures -- no vectorization, no chunking, no streaming. `backend/security.py` caps uploads at `MAX_ROWS=100_000` / 10MB precisely because this ceiling is real, not a formality.

DuckDB (`backend/db.py`) is used only for **persisting a run's results** (the `runs`, `matches`, `exceptions`, `bridges` tables) -- it plays no role in the matching computation itself. The most expensive stage is Stage 5's fuzzy match, which is at least `O(residue_bank × residue_settlement)` (rapidfuzz scoring every remaining candidate pair); it's bounded in practice by only ever running over Stage 1's leftover residue rather than the full dataset, but that bound is still quadratic in the worst case where most rows fail exact UTR matching.

The natural out-of-core path, not yet built, is to push ingestion and Stage 1/3's exact-match candidate generation into DuckDB SQL (join on UTR / order_id directly against on-disk tables) and reserve the in-memory Python cascade for the genuinely fuzzy stages operating on the much smaller residue -- turning the current "everything fits in memory" ceiling into "only the unresolved residue needs to fit in memory."
