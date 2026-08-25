# Fuzzy auto-match threshold sweep

Stage 5's auto_match_threshold (config/settings.yaml, currently 0.90) swept
from 0.60 to 0.95 in 0.05 steps against the committed demo dataset, holding
every other stage fixed. This is the evidence behind the threshold choice
rather than an assertion of it.

| Threshold | Precision | Recall | FP cost (INR) |
|---|---|---|---|
| 0.60 | 1.000 | 1.000 | Rs 0.00 |
| 0.65 | 1.000 | 0.933 | Rs 0.00 |
| 0.70 | 1.000 | 0.833 | Rs 0.00 |
| 0.75 | 1.000 | 0.833 | Rs 0.00 |
| 0.80 | 1.000 | 0.833 | Rs 0.00 |
| 0.85 | 1.000 | 0.767 | Rs 0.00 |
| 0.90 | 1.000 | 0.733 | Rs 0.00 |
| 0.95 | 1.000 | 0.600 | Rs 0.00 |

Precision does not degrade anywhere in this sweep -- every planted bad candidate in this demo dataset scores well below 0.60, and the near-tie ambiguity rule (a separate, fixed safety net) already catches the cases designed to be genuinely ambiguous regardless of this threshold. That means 0.90 is a conservative choice made for safety margin against data this sweep hasn't seen, not because a lower threshold visibly costs precision here -- the honest reading of this specific sweep is that a lower threshold would trade nothing away on this dataset.
