"""Reads evaluation/results/*.md (written by `make eval` / evaluation.ablation)
for the Metrics tab. Parses the committed markdown tables rather than
re-running the pipeline 13 times inside a Streamlit request -- these files
are the same numbers judges would get running `make eval` themselves.
"""

from __future__ import annotations

from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent.parent / "evaluation" / "results"


def _parse_table(text: str) -> list[dict[str, str]]:
    lines = [line for line in text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return []
    header = [cell.strip() for cell in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[2:]:  # skip header + the |---|---| separator row
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        rows.append(dict(zip(header, cells)))
    return rows


def _trailing_note(text: str) -> str:
    """The prose paragraph(s) after the table -- everything past the last
    table row, which is where both ablation.md and threshold_sweep.md put
    their honest-reporting note."""
    lines = text.splitlines()
    last_table_line = max((i for i, line in enumerate(lines) if line.strip().startswith("|")))
    return "\n".join(lines[last_table_line + 1 :]).strip()


class EvalReportMissing(Exception):
    pass


def load_ablation() -> tuple[list[dict[str, str]], str]:
    path = RESULTS_DIR / "ablation.md"
    if not path.exists():
        raise EvalReportMissing(f"{path} not found -- run `make eval` first.")
    text = path.read_text()
    return _parse_table(text), _trailing_note(text)


def load_threshold_sweep() -> tuple[list[dict[str, str]], str]:
    path = RESULTS_DIR / "threshold_sweep.md"
    if not path.exists():
        raise EvalReportMissing(f"{path} not found -- run `make eval` first.")
    text = path.read_text()
    return _parse_table(text), _trailing_note(text)
