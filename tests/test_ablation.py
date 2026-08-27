from dataclasses import dataclass, field

from evaluation.ablation import (
    CUMULATIVE_CONFIGS,
    THRESHOLD_SWEEP,
    _count_real_llm_annotations,
    run_cumulative_ablation,
    run_threshold_sweep,
)


@dataclass
class _FakeException:
    detail: dict = field(default_factory=dict)


@dataclass
class _FakeResult:
    exceptions: list = field(default_factory=list)


def test_count_real_llm_annotations_all_real():
    result = _FakeResult(
        exceptions=[
            _FakeException(
                detail={
                    "llm_root_cause": {"confidence": 0.9},
                    "llm_adjustment_draft": {"memo": "a real suggested entry"},
                }
            )
        ]
    )
    assert _count_real_llm_annotations(result) == (2, 2)


def test_count_real_llm_annotations_all_fallback():
    """Regression test: this is exactly what a real NVIDIA/DeepSeek run
    produced when every one of ~90 live calls hit a 429 -- model_string
    was a real model name (adapter constructed fine), but zero individual
    calls actually succeeded. adapter.model_string alone can't tell the
    two states apart; this function is what can."""
    result = _FakeResult(
        exceptions=[
            _FakeException(
                detail={
                    "llm_narration_classification": {"confidence": 0.0},
                    "llm_root_cause": {"confidence": 0.0},
                    "llm_adjustment_draft": {
                        "memo": "Deterministic fallback; no LLM adjustment generated."
                    },
                }
            )
        ]
    )
    assert _count_real_llm_annotations(result) == (0, 3)


def test_count_real_llm_annotations_mixed():
    result = _FakeResult(
        exceptions=[
            _FakeException(detail={"llm_root_cause": {"confidence": 0.85}}),
            _FakeException(detail={"llm_root_cause": {"confidence": 0.0}}),
        ]
    )
    assert _count_real_llm_annotations(result) == (1, 2)


def test_count_real_llm_annotations_ignores_exceptions_with_no_llm_fields():
    result = _FakeResult(exceptions=[_FakeException(detail={"rule_id": "SOME_RULE"})])
    assert _count_real_llm_annotations(result) == (0, 0)


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
