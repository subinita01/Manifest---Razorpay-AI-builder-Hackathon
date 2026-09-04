# MANIFEST System Architecture Documentation

## 📋 Executive Summary

**MANIFEST** is a deterministic payment reconciliation auditor that matches three financial data sources (bank statements, settlement batches, and internal ledgers) through a six-stage cascading pipeline. The system is designed with a clear separation of concerns: **deterministic core logic** that never uses AI, and an **optional advisory LLM layer** that can only explain or suggest—never decide.

**Core Philosophy:** Tell you what couldn't be matched, not pretend everything matches perfectly.

---

## 🏗️ System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER INTERFACE LAYER                         │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Streamlit Web App (app/streamlit_app.py)                   │   │
│  │  - 6 Tabs: Home, Upload, Run, Bridge, Manifest, Metrics    │   │
│  │  - Real-time reconciliation results                         │   │
│  │  - Interactive bridge waterfall charts                      │   │
│  │  - Exception filtering & export                            │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│                        API & BACKEND LAYER                          │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  FastAPI Routes (backend/routes.py)                         │   │
│  │  - POST /ingest (file upload validation)                    │   │
│  │  - POST /reconcile (trigger pipeline)                       │   │
│  │  - GET /run/{id}, /bridge/{id}, /manifest/{id}             │   │
│  │  - GET /metrics/{id} (precision/recall scoring)            │   │
│  │  - Rate limiter: 10 requests/minute                         │   │
│  └──────────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  DuckDB Persistence (backend/db.py)                         │   │
│  │  - 4 Tables: runs, matches, exceptions, bridges             │   │
│  │  - DECIMAL(18,4) for money precision (no REAL floats)       │   │
│  │  - Indexed by run_id and idempotency_key                    │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    RECONCILIATION CORE (No AI)                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  6-Stage Deterministic Cascade (core/pipeline.py)           │   │
│  │                                                              │   │
│  │  Stage 1: UTR Exact Match                                   │   │
│  │  Stage 2: Gross-to-Net Bridge                               │   │
│  │  Stage 3: Order-to-Ledger Match                             │   │
│  │  Stage 4: TDS Code Migration Validation                     │   │
│  │  Stage 5: Fuzzy Match (last resort)                         │   │
│  │  Stage 6: Exception Classification                          │   │
│  │                                                              │   │
│  │  Invariant Check: matched + needs_review + exceptions       │   │
│  │                   == total_input_rows (MUST always hold)    │   │
│  └──────────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Configuration & Models (config/, core/models.py)           │   │
│  │  - TDS code legacy→new mappings                             │   │
│  │  - Chart of accounts validation                             │   │
│  │  - Tolerance thresholds for amount matching                 │   │
│  │  - Fuzzy match scoring weights                              │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│                 OPTIONAL ADVISORY LAYER (AI Guardrails)             │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  LLM Enrichment (llm/enrich.py) - ADVISORY ONLY              │   │
│  │  - CAN: draft explanations, suggest adjustments              │   │
│  │  - CANNOT: reclassify matches, clear exceptions              │   │
│  │  - Three enrichments per exception:                          │   │
│  │    • narration_classification                               │   │
│  │    • root_cause_explanation                                 │   │
│  │    • adjustment_draft                                       │   │
│  └──────────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  LLM Guardrails (llm/advisory.py)                            │   │
│  │  - Untrusted data wrapping (<untrusted_data> tags)          │   │
│  │  - Field pruning (max 12 fields per prompt)                  │   │
│  │  - Temperature=0, max 1 retry                                │   │
│  │  - Hallucination guard on account names                      │   │
│  │  - Adversarial prompt injection tests                        │   │
│  └──────────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  LLM Providers                                               │   │
│  │  - Primary: Anthropic (ANTHROPIC_API_KEY)                    │   │
│  │  - Fallback: NVIDIA API (free tier, NVIDIA_API_KEY)          │   │
│  │  - If neither: NullAdapter (deterministic stub)              │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│                      AUDIT & SECURITY                               │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Hash-Chained Audit Log (backend/audit_log.py)              │   │
│  │  - Every decision recorded with SHA256 fingerprint           │   │
│  │  - Tamper detection: chain breaks if any entry edited        │   │
│  │  - Idempotency: same input→same run_id (no duplicates)      │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📊 Data Flow: Request to Result

### **Flow 1: Upload & Validation**

```
User Upload (3 CSV files)
    ↓
[Validate file sizes + row counts]
    ↓ [T-CSV security: sanitize narration; prevent formula injection]
    ↓
Store to /data/datasets/{dataset_id}/
    ↓
Return: dataset_id (UUID) + validation summary
    ✓ No pipeline run yet — upload is pure ingestion
```

**Key Security:** 
- Filenames never used in path (always server-chosen names)
- Row limit enforced: max 50,000 per file
- File size limit: prevents OOM attacks

---

### **Flow 2: Reconciliation Pipeline**

```
POST /reconcile { dataset_id, use_llm, fuzzy_threshold }
    ↓
Load CSVs → Parse & Type Cast (core/ingest.py)
    ├─ bank_statement.csv   → Bank rows (narration sanitized)
    ├─ settlement_batch.csv → Settlement rows
    └─ internal_ledger.csv  → Ledger rows
    ↓
┌─── DETERMINISTIC CORE (core/pipeline.py) ───┐
│                                             │
│ Stage 1: UTR Exact Match                    │
│   • Bank credit + Settlement UTR            │
│   • Match if: UTR match (case-insensitive)  │
│   •         + amount within tolerance       │
│   • Output: matched[], residue_bank[]       │
│            residue_settlement[]             │
│                                             │
│ Stage 2: Gross-to-Net Bridge Audit          │
│   • For each Stage 1 match:                 │
│     Gross - MDR - GST + Refunds = Expected  │
│   • Compare: expected vs. actual bank $$    │
│   • Flags: FEE_VARIANCE, RATE_MISMATCH      │
│                                             │
│ Stage 3: Order-to-Ledger Match              │
│   • Settlement order_id ←→ Ledger row       │
│   • Matches TDS information                 │
│   • Output: matched[], residue_ledger[]     │
│            residue_settlement[]             │
│                                             │
│ Stage 4: TDS Code Migration Check           │
│   • For each Stage 3 match with TDS:        │
│   • Validate legacy → new code mapping      │
│   • Flags: INVALID_TDS_CODE, MISMATCH       │
│                                             │
│ Stage 5: Fuzzy Match on Residue             │
│   • Only unmatched rows from Stage 1        │
│   • Score = 0.5·amount + 0.2·date +         │
│             0.3·narration (token_set_ratio) │
│   • Output: matched[], needs_review[]       │
│            ambiguous[] (low confidence)     │
│                                             │
│ Stage 6: Exception Classification           │
│   • Assign taxonomy codes to unmatchesd     │
│   • Codes: SETTLEMENT_ONLY, LEDGER_ONLY,    │
│           BANK_ONLY, AMBIGUOUS, UNEXPLAIN. │
│   • Severity: CRITICAL, WARN, INFO         │
│                                             │
└─────────────────────────────────────────────┘
    ↓
RunResult {
  matched: MatchResult[],         # Confident matches
  needs_review: MatchResult[],    # Low-confidence fuzzy
  exceptions: Exception_[],       # Unmatched + flagged
  stage_results: {...},           # Audit trail
  bridges: {utr → BridgeResult}, # Waterfall data
  invariant_check: PASS/FAIL      # Core verification
}
    ↓
[IF use_llm=true] → llm/enrich.py
    • Narration classification (bank intent)
    • Root-cause narrative (why can't match)
    • Adjustment draft (suggested fix)
    ↓ [Only adds 3 new detail fields; never changes match status]
    ↓
Save to DuckDB (backend/db.py)
    ├─ runs: run_id, counts, config, timestamps
    ��─ matches: bank/settlement/ledger pairs
    ├─ exceptions: taxonomy, severity, detail
    └─ bridges: waterfall steps, residuals, rules
    ↓
Return: RunStatusResponse {
  run_id: UUID,
  status: "completed",
  summary: { total, matched, needs_review, exception }
}
```

---

## 🗂️ Data Models

### **Input Models (CSV → Python Dict)**

```python
# Bank Statement Row
{
  row_id: int,                    # 0-based index
  narration: str,                 # (sanitized, T-CSV)
  credit: Decimal(18,4),          # Money amount
  txn_date: date,                 # Transaction date
  ref_no: str | None,             # Reference number
}

# Settlement Batch Row
{
  settlement_id: str,             # Unique ID
  settlement_utr: str,            # Bank reference
  amount: Decimal(18,4),          # Gross settlement
  fee: Decimal(18,4),             # Gateway fee
  tax: Decimal(18,4),             # Tax on fee
  on_hold: bool,                  # On-hold status
  type: str,                       # "SETTLEMENT" | "REFUND" | "DISPUTE"
  settled_at: datetime,           # Settlement timestamp
  order_id: str | None,           # Associated order
  dispute_id: str | None,         # Dispute reference
}

# Internal Ledger Row
{
  order_id: str,                  # Unique order ID
  gross_amount: Decimal(18,4),    # Order value
  tds_section_legacy: str | None, # Old TDS code (94(o), etc.)
  tds_code_new: str | None,       # New TDS code (194O, etc.)
  tds_amount: Decimal(18,4),      # TDS withholding
  vendor_pan_masked: str,         # Vendor PAN (masked)
  posted_at: datetime,            # GL posting time
}
```

---

### **Core Output Models**

```python
# Match Result (matched + needs_review rows)
@dataclass
class MatchResult:
  match_id: str,                  # UUID
  bank_row_id: int | None,
  settlement_row_id: str | None,
  ledger_row_id: str | None,
  stage_name: str,                # "stage1_utr" | "stage5_fuzzy"
  confidence: float,              # 0.0-1.0 score
  detail: dict,                   # Stage-specific data

# Exception (unmatched or flagged rows)
@dataclass
class Exception_:
  exception_id: str,              # UUID
  taxonomy_code: str,             # See taxonomy table below
  severity: Severity,             # CRITICAL | WARN | INFO
  row_ids: list[str],             # Rows involved
  amount_impact: Decimal(18,4),   # Financial impact in Rs
  detail: dict,                   # Root cause data + LLM enrichments
    # detail keys:
    # - stage_name, reason (deterministic)
    # - llm_narration_classification (advisory)
    # - llm_root_cause (advisory)
    # - llm_adjustment_draft (advisory)

# Bridge Result (Gross → Net waterfall for a UTR group)
@dataclass
class BridgeResult:
  steps: BridgeStep[],            # [Gross → ... → Net]
  expected_net: Decimal(18,4),    # Calculated net
  bank_credit: Decimal(18,4),     # Actual bank credit
  residual: Decimal(18,4),        # Difference
  closed: bool,                   # residual ≈ 0
  attribution: Finding | None,    # Why residual exists
  rate_variance: Finding | None,  # Contracted vs. actual rate
```

---

### **Exception Taxonomy**

| Code | Severity | Meaning |
|------|----------|---------|
| `SETTLEMENT_ONLY` | WARN | In settlement batch, no matching ledger row |
| `LEDGER_ONLY` | WARN | In internal ledger, no settlement entry |
| `BANK_ONLY` | WARN | In bank statement, no settlement UTR |
| `AMBIGUOUS` | WARN | Multiple possible matches (Stage 1) |
| `FEE_VARIANCE` | WARN | Bridge doesn't close; fee rate mismatch |
| `RATE_MISMATCH` | CRITICAL | Recorded rate ≠ contracted rate |
| `INVALID_TDS_CODE` | CRITICAL | TDS code not in config/tds_code_map.yaml |
| `TIMING_T_PLUS_N` | WARN | Date tolerance exceeded |
| `UNEXPLAINED` | INFO | No match theory after all 6 stages |

---

## 🗄️ Database Schema (DuckDB)

### **Table: `runs`**

Metadata for each reconciliation run.

```sql
CREATE TABLE runs (
  run_id TEXT PRIMARY KEY,           -- UUID
  dataset_id TEXT,                   -- "demo" | UUID
  seed INTEGER,                      -- For reproducible synthetic data
  git_sha TEXT,                      -- Git commit (or null)
  config_hash TEXT,                  -- Config version identifier
  model_string TEXT,                 -- Model used ("claude-3.5-sonnet" | "none")
  library_versions TEXT,             -- JSON: {streamlit: x.y.z, ...}
  created_at TIMESTAMP,
  use_llm BOOLEAN,                   -- Whether enrichment ran
  fuzzy_threshold DECIMAL(5,4),      -- Stage 5 auto-match cutoff
  idempotency_key TEXT UNIQUE,       -- Dedup identical inputs
  total_input_rows INTEGER,
  matched_row_count INTEGER,
  needs_review_row_count INTEGER,
  exception_row_count INTEGER
);
```

### **Table: `matches`**

Matched or needs_review results.

```sql
CREATE TABLE matches (
  run_id TEXT,
  match_id TEXT,
  bucket TEXT,                      -- "matched" | "needs_review"
  stage_name TEXT,                  -- "stage1_utr" | "stage5_fuzzy"
  bank_row_id TEXT | NULL,
  settlement_row_id TEXT | NULL,
  ledger_row_id TEXT | NULL,
  confidence DOUBLE,                -- 0.0-1.0
  detail TEXT                       -- JSON: {reason, amounts, ...}
);
```

### **Table: `exceptions`**

Unmatched and flagged rows.

```sql
CREATE TABLE exceptions (
  run_id TEXT,
  exception_id TEXT,
  taxonomy_code TEXT,               -- See taxonomy table
  severity TEXT,                    -- "CRITICAL" | "WARN" | "INFO"
  row_ids TEXT,                     -- JSON array of row identifiers
  amount_impact DECIMAL(18,4),      -- Rs impact
  detail TEXT                       -- JSON: {reason, llm_*, ...}
);
```

### **Table: `bridges`**

Gross-to-net waterfall audits.

```sql
CREATE TABLE bridges (
  run_id TEXT,
  settlement_utr TEXT,              -- Composite key
  steps TEXT,                       -- JSON: [{label, amount, running_total, ...}]
  expected_net DECIMAL(18,4),
  bank_credit DECIMAL(18,4),
  residual DECIMAL(18,4),
  closed BOOLEAN,                   -- Residual ≈ 0
  attribution TEXT,                 -- JSON: {rule, detail}
  rate_variance TEXT                -- JSON: {rule, detail}
);
```

---

## 🔐 Security & Auditability

### **Threat Model & Controls**

| Threat | Control | Location |
|--------|---------|----------|
| CSV Formula Injection | `sanitize_cell()` wraps narration with `'` prefix | `core/normalize.py` |
| Unauthorized file access | `UnsafePath` validation; no `..` in dataset_id | `backend/security.py` |
| OOM attack (huge files) | Row limit: 50k/file; file size limit: 10GB | `backend/routes.py` |
| Silent match falsification | Invariant check: every row accounted for | `core/pipeline.py:184-189` |
| Audit log tampering | SHA256 chain: prev_hash links each entry | `backend/audit_log.py` |
| Prompt injection (LLM) | `<untrusted_data>` tags; field pruning; temp=0 | `llm/prompts.py`, `llm/advisory.py` |
| Duplicate reconciliations | Idempotency key (MD5 of input) → same run_id | `backend/db.py:93-99` |

### **Audit Trail**

```json
{
  "timestamp": "2026-09-04T12:34:56Z",
  "prev_hash": "abc123...",       // Links to previous entry
  "event": {
    "event": "ingest",
    "dataset_id": "uuid-...",
    "validation": {...}
  },
  "hash": "def456..."              // SHA256(prev_hash + content)
}
```

Chain is verified via `get_audit_logger().verify_chain()` before UI sign-off.

---

## 📊 Configuration & Tolerances

### **Location:** `config/`

```yaml
# tolerances.yaml
settlement_amount_tolerance_percent: 0.01  # 1% for Stage 1 UTR match
date_tolerance_days: 2                     # T+2 settlement timing
fuzzy_match:
  auto_match_threshold: 0.90                # Stage 5 auto-cut
  scoring_weights:
    amount: 0.5
    date: 0.2
    narration: 0.3

# tds_code_map.yaml (FY 2026-27 migration)
section_195:
  legacy: "195"
  new_code: "194O"
  verified: false                   # Placeholder pending audit
```

---

## 🚀 Deployment & Infrastructure

### **Runtime Stack**

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **UI** | Streamlit 1.28+ | Interactive web dashboard |
| **API** | FastAPI + slowapi | HTTP reconciliation service |
| **DB** | DuckDB 0.9+ | In-process OLAP (results only) |
| **Python** | 3.11+ | Execution environment |
| **LLM** | Anthropic Claude 3.5 Sonnet OR NVIDIA (optional) | Advisory enrichment |

### **Deployment Modes**

1. **Streamlit Demo** (current)
   - Single process: app + API + DB in-memory
   - No external services needed
   - Live at: `manifest---razorpay-ai-builder-hackathongit-gqvpypgmk6jyx9fq3a.streamlit.app`

2. **Standalone FastAPI** (for production)
   - Separate API server
   - DuckDB → PostgreSQL for scale
   - Deploy via Docker + K8s

### **Scaling Limits (Current)**

- **Input size:** 50k rows per file (memory constraint)
- **Concurrent runs:** Limited by single Python process
- **Throughput:** ~600 rows/second on demo hardware
- **Future:** Push Stage 1/3 exact matches into DuckDB SQL (out-of-core)

---

## 🧪 Testing & Evaluation

### **Test Coverage**

```
tests/
├── test_matching.py           # Stage 1-6 unit tests
├── test_pipeline.py           # Invariant checks
├── test_prompt_injection.py    # LLM safety (adversarial)
├── test_security.py           # Path traversal, formula injection
└── test_audit_chain.py        # Tamper detection
```

### **Evaluation Reports**

```
evaluation/
├── results/
│   ├── ablation.md            # Stage-by-stage contribution
│   └── threshold_sweep.md     # Fuzzy threshold tuning
└── metrics.py                 # Precision, recall, F1
```

**Key Metrics on Demo (seed=42, 600 orders):**
- Auto-match rate: 62.9%
- Matcher precision: 1.000 (zero false positives)
- Matcher recall: 0.733
- Unexplained (by design): 3 rows
- Total exceptions: 45 (covering 269 of 1,273 rows)

---

## 📈 Data Flow Diagram: Exception Lifecycle

```
Unmatched Row from Any Stage
         ↓
    Stage 6: Classify
    (assign taxonomy code)
         ↓
    Exception_ {
      taxonomy_code: str,
      severity: Severity,
      detail: dict
    }
         ↓
[IF use_llm=true]
         ↓
    llm/enrich.py:
    • Wrap narration in <untrusted_data>
    • Prune to 12 fields max
    • Call LLM with temp=0
         ↓
    Add to detail:
    • llm_narration_classification
    • llm_root_cause
    • llm_adjustment_draft
         ↓
    Hallucination Guard:
    • Validate account names
    • Fall back to safe defaults
         ↓
[Save to DB]
         ↓
UI: Manifest Tab
    • Filter by taxonomy / severity
    • Expand for detail + LLM context
    • Ask live Q&A over exceptions
    • Export to CSV
```

---

## 🔄 Request-Response Cycle Examples

### **Example 1: Upload & Validate**

**Request:**
```bash
POST /ingest
Content-Type: multipart/form-data

bank_statement: <file>
settlement_batch: <file>
internal_ledger: <file>
```

**Response:**
```json
{
  "dataset_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "validated",
  "validation": {
    "bank_statement": {"size_bytes": 45230, "rows": 600},
    "settlement_batch": {"size_bytes": 38120, "rows": 687},
    "internal_ledger": {"size_bytes": 29400, "rows": 600}
  }
}
```

---

### **Example 2: Run Reconciliation**

**Request:**
```bash
POST /reconcile
Header: Idempotency-Key: md5(input_hashes)

{
  "dataset_id": "550e8400-...",
  "use_llm": true,
  "fuzzy_threshold": 0.90
}
```

**Response:**
```json
{
  "run_id": "660e8400-e29b-41d4-a716-446655440001",
  "status": "completed",
  "summary": {
    "total_input_rows": 1887,
    "matched_row_count": 1002,
    "needs_review_row_count": 3,
    "exception_row_count": 269
  }
}
```

---

### **Example 3: Retrieve Exception Details**

**Request:**
```bash
GET /manifest/660e8400-e29b-41d4-a716-446655440001
```

**Response (first exception):**
```json
{
  "run_id": "660e8400-...",
  "exceptions": [
    {
      "exception_id": "exc_001",
      "taxonomy_code": "SETTLEMENT_ONLY",
      "severity": "WARN",
      "row_ids": ["settlement_123"],
      "amount_impact": "5000.00",
      "detail": {
        "stage_name": "stage3_order",
        "reason": "Settlement row has order_id=ord_999 but no ledger row found",
        "llm_narration_classification": {
          "category": "timing_delay",
          "confidence": 0.87,
          "explanation": "Narration suggests T+2 settlement; check banking holiday"
        },
        "llm_root_cause": {
          "explanation": "Settlement processed but ledger posting delayed by 2 days",
          "suggested_action": "Verify posting date in GL; common in weekend settlements"
        },
        "llm_adjustment_draft": {
          "account": "10001",  // Validated against chart_of_accounts.yaml
          "amount": "5000.00",
          "description": "Post-settle reconciling item: ord_999 ledger delay"
        }
      }
    }
  ]
}
```

---

## 🎯 Key Design Principles

1. **Determinism First**
   - Core pipeline never imports `llm/`
   - Reproducible: same input → same output
   - No randomness except LLM advisory (which is optional)

2. **Invariant Guarantees**
   - Every row accounted for: `matched + needs_review + exceptions == total`
   - Loud failure (exception) vs. silent forced match
   - Audit trail for every decision

3. **AI as Advisory, Never Arbiter**
   - LLM can explain, suggest, draft
   - LLM cannot reclassify matches or clear exceptions
   - All LLM outputs wrapped in `<untrusted_data>` tags

4. **Precision > Recall**
   - Zero false positives (1.0 precision on demo)
   - Acceptable recall: 0.733 (67% unmatched is better than 100% false confidence)
   - "UNEXPLAINED" is success, not failure

5. **Auditability**
   - Hash-chained audit log
   - Config versioning (config_hash per run)
   - Full evaluation metrics reproducible via `make eval`

---

## 📚 File Structure Reference

```
Manifest/
├── app/
│   ├── streamlit_app.py          # 6-tab UI
│   ├── formatting.py             # Display helpers
│   ├── bridge_presets.py         # Bridge picker logic
│   └── eval_reports.py           # Load ablation/sweep data
│
├── backend/
│   ├── routes.py                 # FastAPI endpoints
│   ├── db.py                     # DuckDB CRUD
│   ├── audit_log.py              # Hash-chained events
│   ├── security.py               # Path/file validation
│   ├── export.py                 # CSV export
│   └── services/
│       └── reconcile_service.py   # Orchestrate pipeline
│
├── core/                         # ❌ NO llm/ imports
│   ├── pipeline.py               # 6-stage runner
│   ├── ingest.py                 # CSV parse & type cast
│   ├── normalize.py              # Sanitization, parsing
│   ├── models.py                 # Data classes
│   ├── taxonomy.py               # Exception codes
│   ├── audit.py                  # Audit trail
│   ├── config.py                 # Load settings
│   └── matching/
│       ├── stage1_utr.py         # Exact UTR match
│       ├── stage2_bridge.py      # Gross→net audit
│       ├── stage3_order.py       # Order match
│       ├── stage4_tds.py         # TDS validation
│       ├── stage5_fuzzy.py       # Fuzzy scoring
│       ├── stage6_classify.py    # Taxonomy assignment
│       └── stage_result.py       # Result container
│
├── llm/                          # 🤖 Advisory only
│   ├── adapter.py                # Provider selection
│   ├── enrich.py                 # Add detail to exceptions
│   ├── advisory.py               # Guardrails
│   ├── prompts.py                # Template library
│   ├── query.py                  # Q&A over exceptions
│   └── anthropic.py              # Anthropic adapter
│
├── config/
│   ├── tolerances.yaml           # Amount/date thresholds
│   ├── tds_code_map.yaml         # 194(o) migration
│   └── chart_of_accounts.yaml    # GL account validation
│
├── data/
│   ├── demo/                     # seed=42 (1,273 rows)
│   ├── sample_upload/            # seed=7 (separate)
│   └── manifest.duckdb           # Results DB
│
├── evaluation/
│   ├── metrics.py                # Precision/recall/F1
│   ├── results/
│   │   ├── ablation.md           # Stage impact
│   │   └── threshold_sweep.md    # Fuzzy tuning
│   └── synthetic_generator.py    # Create test data
│
└── tests/
    ├── test_matching.py          # Stage unit tests
    ├── test_pipeline.py          # Invariant
    ├── test_prompt_injection.py  # LLM safety
    ├── test_security.py          # Path/formula injection
    └── test_audit_chain.py       # Tamper detection
```

---

## 🚨 Known Limitations & Future Work

### **Current Limitations**

1. **In-memory matching:** All 3 CSVs loaded to RAM
   - Workaround: 50k row limit per file
   - Future: Push Stage 1/3 to DuckDB SQL

2. **TDS code map incomplete:** All entries marked `verified: false`
   - Reason: Pending FY 2026-27 audit
   - Impact: TDS mismatches flagged but not auto-corrected

3. **No real bank/Razorpay integration:** CSV in/out only
   - Limitation: Demo-only (no production data pipelines)

4. **No multi-tenancy:** Single dataset per streamlit session
   - Limitation: Not a SaaS product

5. **DuckDB only for results:** Not used in matching
   - Limitation: Scaling to 1M+ rows requires refactor

### **Future Enhancements**

- [ ] Out-of-core matching via DuckDB SQL (stage 1/3)
- [ ] Real Razorpay settlement API integration
- [ ] PostgreSQL backend for multi-tenant deployment
- [ ] Webhook notifications on exception detection
- [ ] Historical trend analysis (settlement patterns)
- [ ] ML-based fuzzy scoring vs. hand-tuned weights

---

## ✅ Verification Checklist for Auditors

- [ ] Invariant holds: `matched + needs_review + exceptions == total_rows`
- [ ] Audit chain verifiable: `GET /audit/{run_id}` + chain validation
- [ ] Precision = 1.0 on demo data (zero false positives)
- [ ] LLM layer optional and isolated (even if disabled, deterministic results match)
- [ ] Config hash recorded per run (reproducibility)
- [ ] No row silently dropped or force-matched
- [ ] Exception taxonomy codes explain structural unmatch reason
- [ ] CSV formula injection sanitized (narration starts with `'`)

---

## 📞 Support & Questions

For architecture questions, refer to:
- **ARCHITECTURE.md** — Design rationale & cascade details
- **SECURITY.md** — Threat model & controls
- **README.md** — Feature overview
- **Code comments** — Implementation details (95%+ test coverage)

---

**Last Updated:** 2026-09-04  
**Version:** 1.0 (System Architecture Documentation)
