import streamlit as st

from backend.services.reconcile_service import ReconcileService
from core.evaluation import build_ablation_table, evaluate_run, load_ground_truth

st.set_page_config(page_title="MANIFEST", page_icon="📘", layout="wide")
st.title("MANIFEST")
st.caption("Settlement, tax-line, and exception auditor")

service = ReconcileService()

if "result" not in st.session_state:
    st.session_state["result"] = service.run_synthetic_check()

with st.sidebar:
    st.subheader("Controls")
    st.toggle("Use LLM advisory", value=False)
    fuzzy_threshold = st.slider(
        "Fuzzy threshold", min_value=0.70, max_value=0.99, value=0.90, step=0.01
    )

    if st.button("Run reconciliation"):
        with st.spinner("Running deterministic reconciliation stages..."):
            st.session_state["result"] = service.run_synthetic_check()
            st.session_state["fuzzy_threshold"] = fuzzy_threshold

upload_tab, run_tab, bridge_tab, manifest_tab, metrics_tab = st.tabs(
    [
        "Upload",
        "Run",
        "Bridge",
        "Manifest",
        "Metrics",
    ]
)

with upload_tab:
    st.info(
        "Demo mode: load the synthetic settlement, bank, and ledger files generated for the run."
    )
    st.file_uploader("Bank statement CSV", type=["csv"])
    st.file_uploader("Settlement batch CSV", type=["csv"])
    st.file_uploader("Internal ledger CSV", type=["csv"])
    st.button("Load demo dataset")

with run_tab:
    result = st.session_state["result"]
    st.success("Engine completed successfully")
    for stage in result["stage_summary"]:
        st.write(f"- {stage['name']}: matched {stage['matched']} | residual {stage['residual']}")

with bridge_tab:
    st.write("Gross → net waterfall")
    st.progress(0.75)
    st.caption(
        "The bridge decomposes settlement totals after MDR, GST, refunds, and reserve adjustments."
    )
    st.code("Gross → Settlement net after MDR, tax, refunds, and on-hold adjustments")

with manifest_tab:
    for exc in st.session_state["result"]["exceptions"]:
        st.code(f"{exc['code']} | {exc['details']}")

with metrics_tab:
    ground_truth = load_ground_truth("data/ground_truth.json")
    metrics = evaluate_run(st.session_state["result"], ground_truth)
    st.metric("Match rate", f"{metrics['match_rate']:.2f}")
    st.metric("Unexplained count", metrics["unexplained_count"])
    st.metric("Expected matches", metrics["expected_matches"])

    st.subheader("Ablation table")
    st.dataframe(build_ablation_table())
