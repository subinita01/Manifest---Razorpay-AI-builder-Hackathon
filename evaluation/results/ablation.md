# Cumulative stage ablation

Each row adds one stage on top of the previous configuration and re-runs the
full pipeline against the committed demo dataset (seed 42, 600 orders).
`make eval` regenerates this file; nothing here is hand-edited.

Match rate/precision/recall/FP cost are all specifically about bank-to-
settlement matching, so Stage 3 (settlement-to-ledger) and Stage 4 (TDS) don't
move them even though they matter a great deal -- that shows up in Total
exceptions instead, which includes SETTLEMENT_ONLY/LEDGER_ONLY findings only
possible once Stage 3 has actually checked the ledger side.

| Configuration | Match rate | Precision | Recall | FP cost (INR) | Total exceptions | Unexplained | Invariant |
|---|---|---|---|---|---|---|---|
| stage1 only | 45.7% | 1.000 | 0.533 | Rs 0.00 | 1257 | 0 | holds |
| + stage2 bridge | 45.7% | 1.000 | 0.533 | Rs 0.00 | 1262 | 0 | holds |
| + stage3 order | 45.7% | 1.000 | 0.533 | Rs 0.00 | 33 | 0 | holds |
| + stage4 tds | 45.7% | 1.000 | 0.533 | Rs 0.00 | 48 | 0 | holds |
| + stage5 fuzzy | 62.9% | 1.000 | 0.733 | Rs 0.00 | 45 | 3 | holds |
| + llm advisory | 62.9% | 1.000 | 0.733 | Rs 0.00 | 45 | 3 | holds |

LLM advisory ran with model_string='none' (no ANTHROPIC_API_KEY, GEMINI_API_KEY, or NVIDIA_API_KEY was set, so this used the deterministic NullAdapter fallback). Every core metric in this row is identical to the '+ stage5 fuzzy' row above -- and by design it always will be, however this row is regenerated: the LLM layer can only append advisory annotations to an exception's detail, never alter which stage matched what (see tests/test_prompt_injection.py, which proves this even against an adversarial adapter). The uplift this row reports is exactly zero, and that's the honest, correct number to report, not a null result to paper over.
