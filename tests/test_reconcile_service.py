from pathlib import Path

import pytest

from backend.db import get_connection, get_run
from backend.security import UnsafePath
from backend.services.reconcile_service import DatasetNotFound, reconcile, resolve_dataset_dir


def test_resolve_dataset_dir_for_demo():
    directory = resolve_dataset_dir("demo")
    assert (directory / "bank_statement.csv").exists()


def test_resolve_dataset_dir_rejects_path_traversal():
    with pytest.raises(UnsafePath):
        resolve_dataset_dir("../../etc")


def test_resolve_dataset_dir_raises_for_unknown_uuid():
    with pytest.raises(DatasetNotFound):
        resolve_dataset_dir("00000000000000000000000000000000")


def test_reconcile_runs_the_real_pipeline_against_demo_data(tmp_path: Path):
    conn = get_connection(tmp_path / "test.duckdb")
    run_id = reconcile(conn, dataset_id="demo", use_llm=False, fuzzy_threshold=0.90)

    stored = get_run(conn, run_id)
    assert stored is not None
    assert stored["dataset_id"] == "demo"
    assert stored["total_input_rows"] > 1000  # the real demo dataset, not a stub
    assert (
        stored["matched_row_count"]
        + stored["needs_review_row_count"]
        + stored["exception_row_count"]
        == stored["total_input_rows"]
    )


def test_reconcile_is_idempotent_for_identical_requests(tmp_path: Path):
    conn = get_connection(tmp_path / "test.duckdb")
    run_id_1 = reconcile(conn, dataset_id="demo", use_llm=False, fuzzy_threshold=0.90)
    run_id_2 = reconcile(conn, dataset_id="demo", use_llm=False, fuzzy_threshold=0.90)
    assert run_id_1 == run_id_2

    # A different fuzzy_threshold is a genuinely different request.
    run_id_3 = reconcile(conn, dataset_id="demo", use_llm=False, fuzzy_threshold=0.80)
    assert run_id_3 != run_id_1


def test_reconcile_honours_explicit_idempotency_key_header(tmp_path: Path):
    conn = get_connection(tmp_path / "test.duckdb")
    run_id_1 = reconcile(
        conn, dataset_id="demo", fuzzy_threshold=0.90, idempotency_key="client-key-1"
    )
    # Even with different params, an explicit matching key returns the cached run.
    run_id_2 = reconcile(
        conn, dataset_id="demo", fuzzy_threshold=0.60, idempotency_key="client-key-1"
    )
    assert run_id_1 == run_id_2


def test_reconcile_with_use_llm_true_produces_the_same_core_decision(tmp_path: Path, monkeypatch):
    """No ANTHROPIC_API_KEY is set in this environment, so use_llm=True
    exercises the real NullAdapter fallback path end to end -- and the
    resulting match/exception counts must be identical to use_llm=False,
    proving the LLM flag genuinely cannot influence the pipeline's own
    decision (see tests/test_prompt_injection.py for the adversarial-
    adapter version of this same guarantee)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    conn_a = get_connection(tmp_path / "a.duckdb")
    run_id_no_llm = reconcile(conn_a, dataset_id="demo", use_llm=False, fuzzy_threshold=0.90)
    no_llm_run = get_run(conn_a, run_id_no_llm)

    conn_b = get_connection(tmp_path / "b.duckdb")
    run_id_with_llm = reconcile(conn_b, dataset_id="demo", use_llm=True, fuzzy_threshold=0.90)
    with_llm_run = get_run(conn_b, run_id_with_llm)

    assert with_llm_run["matched_row_count"] == no_llm_run["matched_row_count"]
    assert with_llm_run["needs_review_row_count"] == no_llm_run["needs_review_row_count"]
    assert with_llm_run["exception_row_count"] == no_llm_run["exception_row_count"]
    assert with_llm_run["model_string"] == "none"  # NullAdapter, no key present
