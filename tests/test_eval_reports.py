import pytest

from app.eval_reports import EvalReportMissing, load_ablation, load_threshold_sweep


def test_load_ablation_parses_all_six_rows():
    rows, note = load_ablation()
    assert len(rows) == 6
    assert rows[0]["Configuration"] == "stage1 only"
    assert rows[-1]["Configuration"] == "+ llm advisory"
    assert "Match rate" in rows[0]
    assert note  # honest LLM-uplift note is non-empty


def test_load_threshold_sweep_parses_eight_rows():
    rows, note = load_threshold_sweep()
    assert len(rows) == 8
    assert rows[0]["Threshold"] == "0.60"
    assert rows[-1]["Threshold"] == "0.95"
    assert note


def test_missing_report_raises(tmp_path, monkeypatch):
    import app.eval_reports as eval_reports

    monkeypatch.setattr(eval_reports, "RESULTS_DIR", tmp_path)
    with pytest.raises(EvalReportMissing):
        load_ablation()
