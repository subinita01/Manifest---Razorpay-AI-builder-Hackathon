from evaluation.ablation import (
    CUMULATIVE_CONFIGS,
    THRESHOLD_SWEEP,
    run_cumulative_ablation,
    run_threshold_sweep,
)


def test_cumulative_ablation_covers_every_configured_stage_and_invariant_holds():
    report = run_cumulative_ablation()
    for name, _ in CUMULATIVE_CONFIGS:
        assert name in report
    assert "VIOLATED" not in report


def test_cumulative_ablation_includes_a_real_llm_advisory_row():
    report = run_cumulative_ablation()
    assert "+ llm advisory" in report
    lines = [line for line in report.splitlines() if line.startswith("|")]
    stage5_row = next(line for line in lines if "+ stage5 fuzzy" in line)
    llm_row = next(line for line in lines if "+ llm advisory" in line)
    # Same core metrics columns (everything except the label itself).
    assert stage5_row.split("|")[2:] == llm_row.split("|")[2:]


def test_threshold_sweep_covers_the_full_range():
    report = run_threshold_sweep()
    assert THRESHOLD_SWEEP[0] == 0.60
    assert THRESHOLD_SWEEP[-1] == 0.95
    assert len(THRESHOLD_SWEEP) == 8
    for threshold in THRESHOLD_SWEEP:
        assert f"{threshold:.2f}" in report
