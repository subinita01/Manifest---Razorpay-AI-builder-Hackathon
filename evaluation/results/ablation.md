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

LLM advisory is not yet implemented (Day 9), so a 6th row cannot be produced honestly; adding a row with no real number behind it would be exactly the kind of unearned claim this project's evaluation exists to prevent.
