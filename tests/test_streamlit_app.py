from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import backend.db as db_module

APP_PATH = str(Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py")


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DEFAULT_DB_PATH", tmp_path / "test.duckdb")
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    return at


def test_app_loads_without_exceptions(app: AppTest):
    assert not app.exception


def test_app_has_five_tabs(app: AppTest):
    assert len(app.tabs) == 5


def test_load_demo_dataset_button_sets_session_state(app: AppTest):
    demo_button = next(b for b in app.button if b.label == "Load demo dataset")
    demo_button.click().run()
    assert not app.exception
    assert app.session_state["dataset_id"] == "demo"


def test_run_reconciliation_end_to_end_populates_manifest(app: AppTest):
    demo_button = next(b for b in app.button if b.label == "Load demo dataset")
    demo_button.click().run()
    assert not app.exception

    run_button = next(b for b in app.button if b.label == "Run reconciliation")
    run_button.click().run()
    assert not app.exception
    assert "run_id" in app.session_state

    run_id = app.session_state["run_id"]
    conn = db_module.get_connection()
    stored = db_module.get_run(conn, run_id)
    assert stored is not None
    assert stored["total_input_rows"] > 1000

    # A second run (re-executing the script with the same session state)
    # should render the Manifest tab's exception expanders without error.
    at2 = app.run()
    assert not at2.exception


def _run_demo(app: AppTest) -> AppTest:
    demo_button = next(b for b in app.button if b.label == "Load demo dataset")
    demo_button.click().run()
    run_button = next(b for b in app.button if b.label == "Run reconciliation")
    return run_button.click().run()


def test_bridge_tab_renders_waterfall_metrics_and_constituent_rows(app: AppTest):
    at = _run_demo(app)
    assert not at.exception
    assert "run_id" in at.session_state

    labels = {m.label for m in at.metric}
    assert "Expected net (per bridge)" in labels
    assert "Bank credit (actual)" in labels

    selectbox_labels = {sb.label for sb in at.selectbox}
    assert "Settlement batch (UTR)" in selectbox_labels
    assert "Step" in selectbox_labels


def test_bridge_doesnt_close_preset_switches_selection(app: AppTest):
    at = _run_demo(app)
    default_utr = at.session_state["bridge_selected_utr"]

    preset_button = next(b for b in at.button if b.label == "Show a bridge that doesn't close")
    assert not preset_button.disabled  # the demo dataset has at least one open bridge
    at = preset_button.click().run()
    assert not at.exception
    assert at.session_state["bridge_selected_utr"] != default_utr


def test_footer_shows_run_manifest_and_verify_chain_button(app: AppTest):
    at = _run_demo(app)
    assert not at.exception

    caption_text = " ".join(c.value for c in at.caption)
    assert "run_id" in caption_text
    assert "git_sha" in caption_text
    assert "config_hash" in caption_text

    verify_button = next(b for b in at.button if b.label == "Verify audit chain")
    at = verify_button.click().run()
    assert not at.exception
    assert at.success or at.error  # the click must produce a real live verdict


def test_ask_about_this_run_falls_back_without_an_api_key(app: AppTest, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    at = _run_demo(app)
    assert not at.exception

    question_input = next(
        t for t in at.text_input if t.label == "Ask a question about these exceptions"
    )
    at = question_input.set_value("Why is ord_00251 flagged?").run()

    ask_button = next(b for b in at.button if b.label == "Ask")
    assert not ask_button.disabled
    at = ask_button.click().run()
    assert not at.exception

    info_text = " ".join(i.value for i in at.info)
    assert "No LLM available" in info_text


def test_metrics_tab_renders_ablation_table_and_unexplained_card(app: AppTest):
    at = _run_demo(app)
    assert not at.exception

    metric_labels = {m.label for m in at.metric}
    assert any("UNEXPLAINED" in label for label in metric_labels)
    assert any("False-positive cost" in label for label in metric_labels)

    ablation_df = next(d.value for d in at.dataframe if "Configuration" in d.value.columns)
    assert "stage1 only" in ablation_df["Configuration"].values
