# MANIFEST Architecture

## High-level design

The project is organized around a deterministic reconciliation engine and an optional LLM advisory layer.

### Layers

1. Upload and validation boundary
2. Deterministic reconciliation core
3. Structured exception taxonomy
4. Optional narration and adjustment advice
5. Audit log and evaluation metrics

## Initial scaffold

- `app/streamlit_app.py` holds the UI shell
- `backend/main.py` exposes the base API surface
- `core/models.py` defines the Pydantic data contracts
- `core/config.py` points to the config and data folders
- `scripts/generate_synthetic_data.py` is the data-generation entry point
- `tests/test_smoke.py` ensures the repo is minimally runnable

## Build plan

1. Create config contract and YAML-driven TDS mapping
2. Add CSV validators and synthetic dataset generator
3. Implement deterministic matching stages 0-6
4. Build FastAPI endpoints and JSON schema responses
5. Connect Streamlit tabs to the backend
6. Add metrics, audit hash chain, and evaluation harness
7. Add security controls and LLM-boundary safeguards
8. Run the full project verification and compile a demo-ready runbook
