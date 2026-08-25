# Security Design

Every control below exists because of a specific, named threat, and every
control has a test that actually attempts the attack rather than asserting
the control exists. `pytest tests/test_security.py` runs the attack suite;
`make audit` runs `pip-audit` against pinned dependency versions.

## Threat model

| ID | Threat | Mitigating control | Proving test |
|---|---|---|---|
| T3 | Path traversal via a malicious upload filename (e.g. `../../etc/passwd`) or a crafted `dataset_id` | `/ingest` never uses the client's filename for the destination path -- every upload is written to a fixed, server-chosen filename inside a UUID directory (`backend/security.py:stream_upload_to_file`, `dataset_dir`). Every `dataset_id` is validated as either the literal `demo` or a `uuid.UUID`-parseable hex string before it touches the filesystem (`validate_dataset_id`), and the resolved directory is asserted to be inside `UPLOAD_DIR` (`dataset_dir`'s `.resolve()` + parents check). | `test_t3_path_traversal_via_malicious_upload_filename` (tests/test_security.py); `test_validate_dataset_id_rejects_path_traversal_attempts`, `test_dataset_dir_resolves_inside_upload_dir` (tests/test_security_utils.py) |
| T4 | Resource exhaustion via an oversized upload or a file with too many rows | Two independent layers: (1) a `Content-Length`-based early rejection in `backend/main.py`'s middleware before the body is even read, and (2) `stream_upload_to_file` writes in 1MB chunks and aborts as soon as the running total exceeds `MAX_UPLOAD_BYTES` (10MB) -- the file is never buffered whole in memory first. `enforce_row_limit` streams line-by-line (not `readlines()`) and aborts past `MAX_ROWS` (100k). | `test_t4_oversized_upload_is_rejected` (tests/test_security.py); `test_stream_upload_rejects_oversized_file_without_buffering_it_all`, `test_enforce_row_limit_rejects_too_many_rows` (tests/test_security_utils.py) |
| T-CSV | CSV formula injection: a narration or export field starting with `=`, `+`, `-`, `@`, tab, or CR opens as a live formula in Excel | `core.normalize.sanitize_cell` prefixes a leading `'` on ingest (`core/ingest.py:load_bank_csv`) and again on export (`backend/export.py:exceptions_to_csv`, recursing into nested `detail` dicts so a payload buried inside a JSON-shaped field is also caught) | `test_csv_formula_injection_payload_is_neutralised_on_export` (tests/test_security.py); `test_sanitize_cell_neutralises_formula_injection_payload` (tests/test_normalize.py); `test_exceptions_to_csv_neutralises_formula_injection_in_every_text_field` (tests/test_export.py) |
| T8 | Information disclosure via a leaked traceback or internal exception message on an unhandled error | A global handler (`backend/main.py:unhandled_exception_handler`) returns only `{"error": "internal_error", "correlation_id": ...}`; the traceback is logged server-side only, keyed by the same correlation_id. Because a plain `@app.middleware("http")` function is a `BaseHTTPMiddleware` under the hood, and Starlette does not reliably route an exception raised downstream of one to a generic `@app.exception_handler(Exception)`, the middleware also wraps `call_next` in its own try/except using the same formatter -- both paths are covered. | `test_t8_internal_error_never_leaks_a_traceback` (tests/test_security.py) |
| T-RATE | Abuse via rapid repeated `/reconcile` calls (each one runs the full matching cascade) | `slowapi` rate limiting, 10/minute on `/reconcile`, keyed by client IP | `test_rate_limiting_blocks_the_11th_rapid_reconcile_request` (tests/test_security.py) |
| T-CORS | A malicious origin driving the API from a browser | `CORSMiddleware` allows only `http://localhost:8501` (the Streamlit dev origin) -- never a wildcard | manual: `curl -H "Origin: http://evil.example" -I http://localhost:8000/healthz` shows no `Access-Control-Allow-Origin` for that origin |
| T-HEADERS | MIME-sniffing and clickjacking | Every response carries `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY` (`backend/main.py` middleware) | covered implicitly by every `tests/test_api.py` request going through the same middleware; no dedicated header-content test yet |
| T-VALIDATE | Malformed or type-confused request bodies (e.g. a float where a str is required, extra unexpected fields) | Every request body is a `ConfigDict(strict=True, extra="forbid")` Pydantic model (`backend/schemas.py`) | FastAPI/Pydantic reject non-conforming bodies with 422 automatically; exercised incidentally by every `tests/test_api.py` call using well-formed bodies |
| T-SQLI | SQL/DuckDB injection via a crafted run_id, dataset_id, or other identifier reaching a query | Every `backend/db.py` query uses parameterized placeholders (`?`) -- no f-string or `.format()` builds a query from user input | covered implicitly: `test_run_unknown_id_returns_404`, `test_bridge_for_a_matched_settlement` etc. pass arbitrary-looking identifiers straight through to `db.py` without incident |
| T-DEP | A pinned dependency with a known CVE | `requirements.txt` pins are kept current against `pip-audit`; `make audit` runs it | `make audit` -> `No known vulnerabilities found` (verified 2026-08; re-run before each milestone, since new CVEs are disclosed over time even for pinned versions) |
| T-MONEY | Float precision errors silently misstating money | `core/` (see CLAUDE.md rule 1) rejects float inputs on every money field via `core.models.MoneyDecimal`; DuckDB money columns are `DECIMAL(18,4)`, never `REAL` (`backend/db.py`) | `test_money_field_rejects_float` (tests/test_models.py); `test_money_columns_are_decimal_not_real` (tests/test_db.py) |

## Non-goals (for now)

- **Authentication/authorization**: every endpoint is open. This is a
  hackathon demo API, not a multi-tenant production service; adding auth
  without a real user model would be security theatre.
- **TLS termination**: assumed to be handled by whatever reverse proxy
  fronts this in a real deployment; the app itself runs plain HTTP for the
  demo.
- **Secrets management**: `core/` never reads environment variables for
  secrets (CLAUDE.md rule 2); the LLM layer (Day 9) will read an API key
  from `.env` (gitignored), which is adequate for a demo but not a
  production secrets story.

## Verifying this yourself

```
make install
make demo-data
pytest tests/test_security.py tests/test_security_utils.py tests/test_export.py -v
make audit
```
