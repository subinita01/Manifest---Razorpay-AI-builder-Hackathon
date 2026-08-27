"""Streamlit UI. Five tabs: Upload, Run, Bridge, Manifest, Metrics. Calls
backend.services.reconcile_service and backend.db directly, in-process --
not over HTTP -- so the demo is a single `streamlit run` with no separate
API server to keep alive.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# `streamlit run app/streamlit_app.py` executes this file directly, which
# puts app/ (not the project root) on sys.path[0] -- every `from app...`,
# `from backend...`, `from core...` import below would fail without this,
# even though `python -m` / pytest's configured pythonpath hides the
# problem (a real bug an AppTest run alone did not catch; only actually
# launching `streamlit run` and hitting it in a browser did).
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app.bridge_presets import pick_clean_default, pick_unresolved_preset  # noqa: E402
from app.eval_reports import EvalReportMissing, load_ablation, load_threshold_sweep  # noqa: E402
from app.formatting import MONOSPACE_CSS, format_int, format_money  # noqa: E402
from backend import db  # noqa: E402
from backend.audit_log import get_audit_logger  # noqa: E402
from backend.export import exceptions_to_csv  # noqa: E402
from backend.security import (  # noqa: E402
    TooManyRows,
    UnsafePath,
    UploadTooLarge,
    dataset_dir,
    enforce_row_limit,
    new_dataset_id,
    stream_upload_to_file_sync,
)
from backend.services.reconcile_service import (  # noqa: E402
    DatasetNotFound,
    reconcile,
    resolve_dataset_dir,
)
from core.config import load_settings  # noqa: E402
from core.ingest import load_settlement_csv  # noqa: E402
from core.taxonomy import Severity  # noqa: E402
from llm.adapter import build_adapter  # noqa: E402
from llm.query import answer_question  # noqa: E402

st.set_page_config(page_title="MANIFEST", page_icon="\U0001f4d8", layout="wide")
st.markdown(MONOSPACE_CSS, unsafe_allow_html=True)


@st.cache_resource
def get_db_connection():
    return db.get_connection()


def _run_summary(run_id: str) -> dict | None:
    return db.get_run(get_db_connection(), run_id)


st.title("MANIFEST")
st.caption("Settlement, tax-line, and exception auditor -- it tells you what it couldn't match.")

upload_tab, run_tab, bridge_tab, manifest_tab, metrics_tab = st.tabs(
    ["Upload", "Run", "Bridge", "Manifest", "Metrics"]
)

# --------------------------------------------------------------------------
# Tab 1: Upload
# --------------------------------------------------------------------------
with upload_tab:
    st.subheader("Load a dataset")

    demo_col, _ = st.columns([1, 2])
    with demo_col:
        if st.button("Load demo dataset", type="primary", width="stretch"):
            st.session_state["dataset_id"] = "demo"
            st.session_state.pop("run_id", None)
            st.success("Demo dataset selected (seed 42, 600 orders). Go to the Run tab.")

    st.divider()
    st.write("Or upload your own bank statement, settlement batch, and internal ledger CSVs:")

    bank_file = st.file_uploader("Bank statement CSV", type=["csv"], key="bank_upload")
    settlement_file = st.file_uploader(
        "Settlement batch CSV", type=["csv"], key="settlement_upload"
    )
    ledger_file = st.file_uploader("Internal ledger CSV", type=["csv"], key="ledger_upload")

    if bank_file and settlement_file and ledger_file:
        if st.button("Validate and use these files"):
            dataset_id = new_dataset_id()
            target_dir = dataset_dir(dataset_id)
            uploads = {
                "bank_statement.csv": bank_file,
                "settlement_batch.csv": settlement_file,
                "internal_ledger.csv": ledger_file,
            }
            validation_rows = []
            failed = False
            for filename, upload in uploads.items():
                destination = target_dir / filename
                try:
                    upload.seek(0)
                    size = stream_upload_to_file_sync(upload, destination)
                    rows = enforce_row_limit(destination)
                    validation_rows.append({"file": filename, "size_bytes": size, "rows": rows})
                except (UploadTooLarge, TooManyRows) as exc:
                    st.error(f"{filename}: {exc}")
                    failed = True
            if not failed:
                st.session_state["dataset_id"] = dataset_id
                st.session_state.pop("run_id", None)
                st.success(f"Validated. dataset_id={dataset_id}")
                st.table(validation_rows)

    current = st.session_state.get("dataset_id")
    if current:
        st.info(f"Active dataset: **{current}**")


# --------------------------------------------------------------------------
# Tab 2: Run
# --------------------------------------------------------------------------
with run_tab:
    dataset_id = st.session_state.get("dataset_id")
    if not dataset_id:
        st.warning("Load a dataset in the Upload tab first.")
    else:
        st.subheader(f"Run reconciliation on `{dataset_id}`")

        col1, col2 = st.columns(2)
        with col1:
            use_llm = st.toggle("Use LLM advisory", value=False)
        with col2:
            fuzzy_threshold = st.slider(
                "Fuzzy auto-match threshold", min_value=0.60, max_value=0.99, value=0.90, step=0.01
            )

        if st.button("Run reconciliation", type="primary"):
            try:
                directory = resolve_dataset_dir(dataset_id)
            except (DatasetNotFound, UnsafePath) as exc:
                st.error(f"Cannot run: {exc}")
            else:
                conn = get_db_connection()
                status = st.status("Running deterministic reconciliation cascade...", expanded=True)

                # Real, cheap-to-read facts about the dataset shown before the
                # (already fast, sub-second) pipeline runs -- a deliberate
                # pause between genuine information, not a fabricated
                # per-stage progress bar with numbers that aren't real yet.
                row_counts = {
                    name: (directory / f"{name}.csv").read_text().count("\n") - 1
                    for name in ("bank_statement", "settlement_batch", "internal_ledger")
                }
                status.write(
                    f"Loaded {format_int(row_counts['bank_statement'])} bank rows, "
                    f"{format_int(row_counts['settlement_batch'])} settlement rows, "
                    f"{format_int(row_counts['internal_ledger'])} ledger rows."
                )
                time.sleep(0.3)
                status.write(
                    "Running Stages 1-6 (UTR match -> bridge -> order match -> "
                    "TDS validation -> fuzzy match -> classify)..."
                )
                run_id = reconcile(
                    conn,
                    dataset_id=dataset_id,
                    use_llm=use_llm,
                    fuzzy_threshold=fuzzy_threshold,
                )
                summary = db.get_run(conn, run_id)
                time.sleep(0.2)
                status.write(
                    f"Done: {format_int(summary['matched_row_count'])} matched, "
                    f"{format_int(summary['needs_review_row_count'])} needs review, "
                    f"{format_int(summary['exception_row_count'])} exceptions "
                    f"(of {format_int(summary['total_input_rows'])} total rows)."
                )
                status.update(label="Reconciliation complete.", state="complete", expanded=False)

                st.session_state["run_id"] = run_id

        run_id = st.session_state.get("run_id")
        if run_id:
            summary = _run_summary(run_id)
            if summary:
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total rows", format_int(summary["total_input_rows"]))
                m2.metric("Matched", format_int(summary["matched_row_count"]))
                m3.metric("Needs review", format_int(summary["needs_review_row_count"]))
                m4.metric("Exceptions", format_int(summary["exception_row_count"]))
                st.caption(f"run_id: `{run_id}`")


# --------------------------------------------------------------------------
# Tab 3: Bridge
# --------------------------------------------------------------------------
with bridge_tab:
    run_id = st.session_state.get("run_id")
    if not run_id:
        st.warning("Run a reconciliation in the Run tab first.")
    else:
        conn = get_db_connection()
        bridge_utrs = db.get_bridge_utrs(conn, run_id)

        if not bridge_utrs:
            st.info("No gross-to-net bridges were computed for this run.")
        else:
            clean_default = pick_clean_default(bridge_utrs)
            open_preset = pick_unresolved_preset(bridge_utrs)

            if "bridge_selected_utr" not in st.session_state:
                st.session_state["bridge_selected_utr"] = clean_default

            preset_col1, preset_col2 = st.columns(2)
            with preset_col1:
                if st.button("Show a bridge that closes cleanly", width="stretch"):
                    st.session_state["bridge_selected_utr"] = clean_default
            with preset_col2:
                if st.button(
                    "Show a bridge that doesn't close",
                    width="stretch",
                    disabled=open_preset is None,
                ):
                    st.session_state["bridge_selected_utr"] = open_preset

            all_utrs = [u["settlement_utr"] for u in bridge_utrs]
            current = st.session_state["bridge_selected_utr"]
            selected_utr = st.selectbox(
                "Settlement batch (UTR)",
                all_utrs,
                index=all_utrs.index(current) if current in all_utrs else 0,
            )
            st.session_state["bridge_selected_utr"] = selected_utr

            bridge = db.get_bridge(conn, run_id, selected_utr)
            steps = bridge["steps"]

            badge = "🟢 CLOSED" if bridge["closed"] else "🔴 OPEN"
            st.markdown(f"### {badge} -- residual Rs {format_money(bridge['residual'])}")

            x_labels = [s["label"] for s in steps] + ["Residual", "Bank credit (actual)"]
            y_values = [float(s["amount"]) for s in steps] + [float(bridge["residual"]), 0]
            measures = ["absolute"] + ["relative"] * (len(steps) - 1) + ["relative", "total"]

            fig = go.Figure(
                go.Waterfall(
                    x=x_labels,
                    y=y_values,
                    measure=measures,
                    text=[f"Rs {v:,.2f}" for v in y_values[:-1]] + [""],
                    textposition="outside",
                    connector={"line": {"color": "rgba(120,120,120,0.4)"}},
                    increasing={"marker": {"color": "#2e7d32"}},
                    decreasing={"marker": {"color": "#c62828"}},
                    totals={"marker": {"color": "#1565c0"}},
                )
            )
            fig.update_layout(
                title=f"Gross-to-net bridge -- UTR {selected_utr}",
                showlegend=False,
                margin=dict(t=50, b=20),
            )
            st.plotly_chart(fig, width="stretch")

            m1, m2 = st.columns(2)
            m1.metric("Expected net (per bridge)", f"Rs {format_money(bridge['expected_net'])}")
            m2.metric("Bank credit (actual)", f"Rs {format_money(bridge['bank_credit'])}")

            if bridge["attribution"]:
                st.warning(
                    f"**Residual attributed to:** {bridge['attribution']['rule']} -- "
                    f"{bridge['attribution']['detail']}"
                )
            if bridge["rate_variance"]:
                st.error(
                    f"**Rate-compliance finding:** {bridge['rate_variance']['rule']} -- "
                    f"the recorded rate does not match the contracted rate on file, even "
                    f"though the settlement's own figures reconcile to what hit the bank. "
                    f"Detail: {bridge['rate_variance']['detail']}"
                )

            st.divider()
            st.write("Constituent rows for a step:")
            steps_with_rows = [s for s in steps if s["constituent_row_ids"]]
            step_labels = [s["label"] for s in steps_with_rows]
            if step_labels:
                chosen_label = st.selectbox("Step", step_labels)
                chosen_step = next(s for s in steps_with_rows if s["label"] == chosen_label)

                stored = db.get_run(conn, run_id)
                try:
                    settlement_dir = resolve_dataset_dir(stored["dataset_id"])
                    settlement_by_id = {
                        r["settlement_id"]: r
                        for r in load_settlement_csv(settlement_dir / "settlement_batch.csv")
                    }
                    rows_for_step = [
                        {
                            "settlement_id": rid,
                            "amount": (
                                format_money(settlement_by_id[rid]["amount"])
                                if rid in settlement_by_id
                                else "?"
                            ),
                            "fee": (
                                format_money(settlement_by_id[rid]["fee"])
                                if rid in settlement_by_id
                                else "?"
                            ),
                            "tax": (
                                format_money(settlement_by_id[rid]["tax"])
                                if rid in settlement_by_id
                                else "?"
                            ),
                            "type": (
                                settlement_by_id[rid]["type"] if rid in settlement_by_id else "?"
                            ),
                        }
                        for rid in chosen_step["constituent_row_ids"]
                    ]
                    st.dataframe(rows_for_step, width="stretch", hide_index=True)
                except (DatasetNotFound, UnsafePath):
                    st.write(chosen_step["constituent_row_ids"])
            else:
                st.caption("No steps in this bridge have constituent rows.")


# --------------------------------------------------------------------------
# Tab 4: Manifest
# --------------------------------------------------------------------------
with manifest_tab:
    run_id = st.session_state.get("run_id")
    if not run_id:
        st.warning("Run a reconciliation in the Run tab first.")
    else:
        conn = get_db_connection()
        exceptions = db.get_exceptions(conn, run_id)

        if not exceptions:
            st.success("No exceptions on this run.")
        else:
            st.markdown("**Ask about this run**")
            question = st.text_input(
                "Ask a question about these exceptions",
                placeholder="Why is row ord_00251 unexplained?",
                label_visibility="collapsed",
            )
            if st.button("Ask", disabled=not question.strip()):
                adapter = build_adapter(api_key=os.environ.get("ANTHROPIC_API_KEY"))
                with st.spinner("Thinking..."):
                    result = answer_question(adapter, question, exceptions)
                st.info(result.answer)
                if result.cited_exception_ids:
                    st.caption(f"Based on: {', '.join(result.cited_exception_ids)}")
                if adapter.model_string == "none":
                    st.caption(
                        "No ANTHROPIC_API_KEY set -- this answer came from the "
                        "deterministic fallback, not a live model."
                    )

            st.divider()
            all_codes = sorted({e["taxonomy_code"] for e in exceptions})
            all_severities = [s.value for s in Severity]

            fcol1, fcol2 = st.columns(2)
            with fcol1:
                selected_codes = st.multiselect("Taxonomy code", all_codes, default=all_codes)
            with fcol2:
                selected_severities = st.multiselect(
                    "Severity", all_severities, default=all_severities
                )

            filtered = [
                e
                for e in exceptions
                if e["taxonomy_code"] in selected_codes and e["severity"] in selected_severities
            ]

            st.caption(
                f"{format_int(len(filtered))} of {format_int(len(exceptions))} exceptions shown"
            )

            severity_order = {"CRITICAL": 0, "WARN": 1, "INFO": 2}
            filtered.sort(key=lambda e: (severity_order.get(e["severity"], 9), e["taxonomy_code"]))

            for exc in filtered:
                label = (
                    f"{exc['severity']:<8} {exc['taxonomy_code']:<28} "
                    f"Rs {format_money(exc['amount_impact'])}"
                )
                with st.expander(label):
                    st.markdown(f"**Row IDs:** `{', '.join(exc['row_ids'])}`")
                    st.markdown("**Detail:**")
                    detail = dict(exc["detail"])
                    llm_root_cause = detail.pop("llm_root_cause", None)
                    llm_adjustment = detail.pop("llm_adjustment_draft", None)
                    llm_narration = detail.pop("llm_narration_classification", None)
                    st.json(detail)

                    if llm_narration:
                        st.markdown("**LLM narration classification:**")
                        st.json(llm_narration)
                    if llm_root_cause:
                        st.markdown("**Root-cause narrative:**")
                        st.write(llm_root_cause.get("explanation", ""))
                        st.caption(
                            f"Suggested action: {llm_root_cause.get('suggested_action', '')}"
                        )
                    if llm_adjustment:
                        st.markdown("**Draft adjustment entry:**")
                        st.json(llm_adjustment)

            csv_text = exceptions_to_csv(filtered)
            st.download_button(
                "Export filtered exceptions (CSV)",
                data=csv_text,
                file_name=f"manifest_{run_id}.csv",
                mime="text/csv",
            )


# --------------------------------------------------------------------------
# Tab 5: Metrics
# --------------------------------------------------------------------------
with metrics_tab:
    st.subheader("Evaluation against the committed demo dataset")
    st.caption(
        "These numbers come from `evaluation/results/*.md`, written by `make eval` -- "
        "the same command a judge can run themselves to get the identical figures."
    )

    try:
        ablation_rows, ablation_note = load_ablation()
        sweep_rows, sweep_note = load_threshold_sweep()
    except EvalReportMissing as exc:
        st.warning(f"{exc}")
    else:
        st.markdown("**Cumulative stage ablation**")
        st.dataframe(ablation_rows, width="stretch", hide_index=True)
        st.info(ablation_note)

        stage5_row = next(
            (r for r in ablation_rows if r["Configuration"] == "+ stage5 fuzzy"), None
        )

        st.divider()
        st.markdown("**Fuzzy auto-match threshold sweep**")
        configured_threshold = float(load_settings()["fuzzy_match"]["auto_match_threshold"])

        thresholds = [float(r["Threshold"]) for r in sweep_rows]
        precisions = [float(r["Precision"]) for r in sweep_rows]
        recalls = [float(r["Recall"]) for r in sweep_rows]

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(x=thresholds, y=precisions, mode="lines+markers", name="Precision")
        )
        fig.add_trace(go.Scatter(x=thresholds, y=recalls, mode="lines+markers", name="Recall"))
        fig.add_vline(
            x=configured_threshold,
            line_dash="dash",
            line_color="gray",
            annotation_text=f"chosen threshold ({configured_threshold:.2f})",
        )
        fig.update_layout(
            xaxis_title="Fuzzy auto-match threshold",
            yaxis_title="Score",
            yaxis_range=[0, 1.05],
            margin=dict(t=20, b=20),
        )
        st.plotly_chart(fig, width="stretch")
        st.caption(sweep_note)

        st.divider()
        fp_col, unexplained_col = st.columns(2)
        with fp_col:
            st.metric(
                "False-positive cost (demo dataset, stage5 config)",
                f"Rs {stage5_row['FP cost (INR)'].replace('Rs ', '')}" if stage5_row else "n/a",
            )

        current_run_id = st.session_state.get("run_id")
        unexplained_value = None
        unexplained_source = ""
        if current_run_id:
            conn = get_db_connection()
            current_exceptions = db.get_exceptions(conn, current_run_id)
            unexplained_value = sum(
                1 for e in current_exceptions if e["taxonomy_code"] == "UNEXPLAINED"
            )
            unexplained_source = "this run"
        elif stage5_row:
            unexplained_value = int(stage5_row["Unexplained"])
            unexplained_source = "demo dataset, last `make eval`"

        with unexplained_col:
            st.metric(
                "UNEXPLAINED -- records this system refused to guess at",
                format_int(unexplained_value) if unexplained_value is not None else "n/a",
            )
            if unexplained_source:
                st.caption(f"Source: {unexplained_source}")


# --------------------------------------------------------------------------
# Footer: RunManifest for the active run, and live audit-chain verification.
# --------------------------------------------------------------------------
st.divider()
footer_run_id = st.session_state.get("run_id")
if footer_run_id:
    footer_run = db.get_run(get_db_connection(), footer_run_id)
    if footer_run:
        f1, f2, f3, f4 = st.columns(4)
        f1.caption(f"**run_id**  \n`{footer_run['run_id']}`")
        f2.caption(f"**seed**  \n{footer_run['seed']}")
        f3.caption(f"**git_sha**  \n`{footer_run['git_sha'] or 'n/a (not a git repo)'}`")
        f4.caption(f"**config_hash**  \n`{footer_run['config_hash']}`")
        f5, f6 = st.columns(2)
        f5.caption(f"**model_string**  \n{footer_run['model_string'] or 'none'}")
        lib_versions = ", ".join(f"{k}={v}" for k, v in footer_run["library_versions"].items())
        f6.caption(f"**library_versions**  \n{lib_versions}")
        st.caption(f"created_at: {footer_run['created_at']}")

if st.button("Verify audit chain"):
    chain_valid = get_audit_logger().verify_chain()
    if chain_valid:
        st.success("Audit chain verified: every record's hash and prev_hash link checks out.")
    else:
        st.error("Audit chain verification FAILED -- a record has been tampered with or removed.")
