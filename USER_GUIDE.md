# 📖 MANIFEST User Guide: Complete Walkthrough

Welcome! This guide walks you through MANIFEST step-by-step, from uploading your first CSV to understanding exception reports. **No finance knowledge required** — we explain everything in plain English.

---

## 🎯 Table of Contents

1. [What is MANIFEST?](#what-is-manifest)
2. [Getting Started (5 minutes)](#getting-started-5-minutes)
3. [Step-by-Step: Upload Your Data](#step-1-upload-your-data)
4. [Step-by-Step: Run Reconciliation](#step-2-run-reconciliation)
5. [Step-by-Step: Review Results](#step-3-review-results)
6. [Understanding Exception Codes](#understanding-exception-codes)
7. [Common Scenarios & How to Fix Them](#common-scenarios--how-to-fix-them)
8. [FAQ](#faq)
9. [Troubleshooting](#troubleshooting)

---

## What is MANIFEST?

**MANIFEST tells you what your money is doing — and what it's NOT doing.**

Imagine you have three spreadsheets:
- **Bank Statement**: "You got Rs 10,000 in the bank today"
- **Settlement Batch**: "We sent you 9 payments totaling Rs 10,500"
- **Ledger**: "We recorded 9 orders totaling Rs 10,500 (minus tax)"

These should match perfectly. But often they don't. MANIFEST **finds every mismatch**, **explains why it happened**, and **never lies and says everything is fine when it isn't**.

### Why This Matters

A reconciliation tool that claims 100% match is either:
- ❌ Lying to you (hiding problems)
- ❌ Force-matching rows that don't belong together
- ❌ Causing tax/audit issues silently

MANIFEST is different. It says:
- ✅ "These 1,002 rows match perfectly"
- ⚠️ "These 3 rows are close but need your review"
- ❌ "These 269 rows don't match — here's why"

---

## Getting Started (5 minutes)

### What You Need

**Option A: Try the Demo (Easiest)**
- No files needed
- Click "Load demo dataset" → Instant results
- Perfect for learning without your own data

**Option B: Use Your Own Files**
- 3 CSV files (download templates below)
- 10 rows minimum; 50,000 rows maximum per file
- File size: under 10GB

### Installation (Local Computer)

```bash
# 1. Install Python (3.11 or newer)
# Download from https://www.python.org/downloads/

# 2. Clone the repository
git clone https://github.com/subinita01/Manifest---Razorpay-AI-builder-Hackathon.git
cd Manifest---Razorpay-AI-builder-Hackathon

# 3. Install dependencies
make install
# (Or: python -m venv .venv && 
#     source .venv/bin/activate &&
#     pip install -r requirements.txt)

# 4. Launch the app
make demo
# (Or: streamlit run app/streamlit_app.py)

# 5. Open in your browser
# http://localhost:8501
```

### Try the Online Demo

**No installation needed!**
👉 Visit: [manifest---razorpay-ai-builder-hackathongit-gqvpypgmk6jyx9fq3a.streamlit.app](https://manifest---razorpay-ai-builder-hackathongit-gqvpypgmk6jyx9fq3a.streamlit.app)

---

## Step 1: Upload Your Data

### Tab: "Upload"

#### Option A: Load Demo Dataset (Simplest)

```
1. Click the blue button: "Load demo dataset"
   ↓
2. You'll see: "Demo dataset selected (seed 42, 600 orders). Go to the Run tab."
   ↓
3. Click on the "Run" tab (top of page)
```

**Why the demo?**
- 600 real-looking orders + ground truth
- See exactly how MANIFEST works
- Takes ~2 seconds to run

---

#### Option B: Upload Your Own CSVs

**Step 1: Prepare Your Files**

You need 3 CSV files:

**File 1: Bank Statement** (`bank_statement.csv`)
```csv
narration,credit,txn_date,ref_no
"NEFT INWARD-abc123",50000.00,2024-01-15,
"RTGS-xyz789",100000.00,2024-01-16,"REF001"
"UPI SETTLEMENT-def456",75000.00,2024-01-17,
```

**Column Explanations:**
- `narration`: What the bank calls this transaction (can be messy)
- `credit`: Amount received (Rs)
- `txn_date`: When it hit your bank (YYYY-MM-DD)
- `ref_no`: Bank reference (optional)

---

**File 2: Settlement Batch** (`settlement_batch.csv`)
```csv
settlement_id,settlement_utr,amount,fee,tax,on_hold,type,settled_at,order_id,dispute_id
"settle_001","UTR-20240115-001",50000.00,1000.00,180.00,"False","SETTLEMENT","2024-01-15T10:30:00","ord_001",
"settle_002","UTR-20240116-002",100000.00,2000.00,360.00,"False","SETTLEMENT","2024-01-16T11:45:00","ord_002",
"settle_003","UTR-20240117-003",75000.00,1500.00,270.00,"False","SETTLEMENT","2024-01-17T09:15:00","ord_003",
```

**Column Explanations:**
- `settlement_id`: Your unique ID for this settlement
- `settlement_utr`: The bank's Unique Transaction Reference (usually in `narration` of bank statement)
- `amount`: Gross amount before fees
- `fee`: Gateway/processing fee
- `tax`: Tax on the fee (GST, etc.)
- `on_hold`: Is money blocked? ("True" or "False")
- `type`: "SETTLEMENT" | "REFUND" | "DISPUTE"
- `settled_at`: When Razorpay/gateway settled (ISO datetime)
- `order_id`: Link to your order (matches ledger)
- `dispute_id`: If this is a dispute settlement (optional)

---

**File 3: Internal Ledger** (`internal_ledger.csv`)
```csv
order_id,gross_amount,tds_section_legacy,tds_code_new,tds_amount,vendor_pan_masked,posted_at
"ord_001",50000.00,"194O","194O",0.00,"XXXXX1234",2024-01-15T12:00:00
"ord_002",100000.00,"195","194O",2000.00,"XXXXX5678",2024-01-16T13:30:00
"ord_003",75000.00,,,"0.00","XXXXX9012",2024-01-17T11:00:00
```

**Column Explanations:**
- `order_id`: Your unique order ID (matches settlement)
- `gross_amount`: Total order value
- `tds_section_legacy`: Old tax withholding code (e.g., "195", "194O")
- `tds_code_new`: New code for FY 2026-27 (e.g., "194O")
- `tds_amount`: How much was withheld
- `vendor_pan_masked`: Vendor's PAN (masked for security)
- `posted_at`: When it hit your general ledger (ISO datetime)

---

**Step 2: Upload to MANIFEST**

1. **In the "Upload" tab**, scroll down past the demo section
2. Click: **"Bank statement CSV"** → Select your `bank_statement.csv`
3. Click: **"Settlement batch CSV"** → Select your `settlement_batch.csv`
4. Click: **"Internal ledger CSV"** → Select your `internal_ledger.csv`
5. A preview appears showing the first 5 rows
6. Click the blue button: **"Validate and use these files"**

**What MANIFEST checks:**
- ✅ File sizes (must be < 10GB each)
- ✅ Row counts (max 50,000 per file)
- ✅ No malicious formulas (e.g., `=SUM(A1:A10)`)
- ✅ Dates are valid (YYYY-MM-DD format)
- ✅ Money amounts are numbers

**Success message:**
```
✓ Validated. dataset_id=550e8400-e29b-41d4-a716-446655440000
```

You'll see your **dataset_id** at the bottom of the screen. This stays active until you upload new files or reload the browser.

---

## Step 2: Run Reconciliation

### Tab: "Run"

**You should already be here.** If not, click the "Run" tab.

#### Setup: Choose Your Settings

```
┌─────────────────────────────────────┐
│ 1. Use LLM advisory?                │
│    Toggle: OFF  [Switch ON]         │
│                                     │
│    What's this?                     │
│    • OFF: Fast, deterministic       │
│    • ON: AI explains exceptions     │
│    (Both give the same matches)     │
│                                     │
│ 2. Fuzzy auto-match threshold       │
│    Slider: 0.60 ←→ 0.99 [0.90]     │
│                                     │
│    What's this?                     │
│    • Higher (0.95): Stricter        │
│      (fewer matches, more review)   │
│    • Lower (0.70): Looser           │
│      (more matches, less review)    │
│                                     │
│ 3. [RUN RECONCILIATION] (blue btn)  │
└─────────────────────────────────────┘
```

**Default Settings Explained:**

| Setting | Default | What It Means |
|---------|---------|---------------|
| Use LLM | OFF | Deterministic only (fastest, predictable) |
| Fuzzy Threshold | 0.90 | Match rows with 90%+ similarity confidence |

**First time?** Leave defaults and click **"Run reconciliation"**.

#### During Reconciliation

You'll see a status box:

```
Running deterministic reconciliation cascade...

✓ Loaded 600 bank rows, 687 settlement rows, 600 ledger rows.

✓ Running Stages 1-6 (UTR match → bridge → order match → 
  TDS validation → fuzzy match → classify)...

✓ Done: 1,002 matched, 3 needs review, 269 exceptions 
  (of 1,887 total rows).

Reconciliation complete.
```

**This means:**
- ✅ 1,002 rows matched perfectly
- ⚠️ 3 rows fuzzy-matched (need human review)
- ❌ 269 rows unmatched (exceptions with explanations)
- 📊 Total: 1,887 rows accounted for (1 + 1 + 1 = 1 ✓)

#### Results Summary

Below the status box, you'll see metrics:

```
Total rows: 1,887
Matched: 1,002 (53.1%)
Needs review: 3 (0.2%)
Exceptions: 269 (14.3%)

run_id: `660e8400-e29b-41d4-a716-446655440001`
```

**What now?**
- Review matched rows: Go to **Bridge** tab
- Review exceptions: Go to **Manifest** tab
- See accuracy metrics: Go to **Metrics** tab

---

## Step 3: Review Results

### Tab: "Bridge"

**The Bridge shows: Gross Money → Net Money**

Think of it like a waterfall:

```
Starting gross settlement: Rs 100,000
├─ Minus: MDR (merchant discount rate): -Rs 2,000
├─ Minus: GST on MDR: -Rs 360
├─ Plus: Refunds: +Rs 0
├─ Plus: Chargebacks: +Rs 0
├─ Minus: On-hold: -Rs 0
├─────────────────────────────────────
= Expected net: Rs 97,640

✓ Bank statement shows credit: Rs 97,640
✓ MATCH! (Residual: Rs 0)
```

**How to use:**

1. **See the green/red badge:**
   - 🟢 **CLOSED**: Residual ≈ 0 (perfect match)
   - 🔴 **OPEN**: Residual > 0 (something's off)

2. **Select a settlement:** Dropdown menu lists all UTRs
   - Buttons help: "Show a bridge that closes cleanly" or "Show a bridge that doesn't close"

3. **Click on a step:** See which settlement rows created that amount

4. **If OPEN (red):**
   - Look at "Residual attributed to" (yellow box)
   - Look at "Rate-compliance finding" (red box)
   - These explain the difference

**Example Exception:**
```
🔴 OPEN -- residual Rs 1,500.00

Residual attributed to: TIMING_DELAY --
The bank credit landed before settlement batch was 
complete. This is normal for same-day settlements.

Action: Check next day's settlement batch; money 
likely moved on T+1.
```

---

### Tab: "Manifest"

**The Manifest is your exception report.**

This is where problems are listed.

#### Natural Language Search

At the top, type a question:

```
Ask a question about these exceptions
[Why is row ord_00251 unexplained?]
                [Ask]
```

MANIFEST's AI reads all exceptions and answers:

```
💡 Answered by: claude-3.5-sonnet

"Row ord_00251 appears in the settlement batch but has 
no matching order in your internal ledger. This typically 
happens when:

1. The order hasn't been posted to GL yet (timing delay)
2. The order_id field is blank or malformed
3. The order was cancelled but the settlement went through

Suggestion: Search your GL for order_id 'ord_00251' 
dated within 2 days of the settlement date."

Based on: exc_087, exc_088, exc_089
  [Click to see details]
```

---

#### Exception List

Below the search, you'll see all exceptions. Filter them:

```
Taxonomy code: [All] [Multiple select dropdown]
Severity: [All] [Multiple select dropdown]

CRITICAL (0)
├─ INVALID_TDS_CODE
├─ RATE_MISMATCH
└─ [None]

WARN (269)
├─ SETTLEMENT_ONLY (180 rows)
├─ LEDGER_ONLY (45 rows)
├─ FEE_VARIANCE (30 rows)
├─ AMBIGUOUS (10 rows)
└─ TIMING_T_PLUS_N (4 rows)

INFO (3)
└─ UNEXPLAINED
```

**Click to expand any exception:**

```
WARN   SETTLEMENT_ONLY   Rs 5,000.00

Row IDs: settlement_123

Detail:
{
  "stage_name": "stage3_order",
  "reason": "Settlement row has order_id=ord_999 but 
            no matching ledger row found"
}

LLM narration classification:
{
  "category": "timing_delay",
  "confidence": 0.87,
  "explanation": "Narration contains 'settlement' which 
                 suggests routine batch processing"
}

Root-cause narrative:
"Settlement processed but ledger posting delayed by 2 days
due to weekend. This is normal in Indian bank cycles."

Suggested action: Verify posting date in GL; check for 
banking holidays (Diwali, year-end).

Draft adjustment entry:
Account: 10001 (Reconciliation)
Amount: Rs 5,000.00
Description: Post-settle reconciling item: ord_999 ledger 
             delay
```

---

#### Export Exceptions

At the bottom, click: **"Export filtered exceptions (CSV)"**

This downloads a CSV with all your exceptions for Excel analysis.

---

### Tab: "Metrics"

**Proof that MANIFEST is accurate.**

You'll see:

```
Cumulative stage ablation

Configuration          Auto-match  Precision  Recall  ...
Base (Stage 1 only)    40.5%       1.000      0.405
+ Stage 2 bridge       41.2%       1.000      0.412
+ Stage 3 order        48.1%       1.000      0.481
+ Stage 4 TDS          48.9%       1.000      0.489
+ Stage 5 fuzzy        62.9%       1.000      0.733

This shows that each stage adds value without 
introducing false positives.
```

**What do these mean?**

| Metric | Definition | Why It Matters |
|--------|-----------|---|
| **Auto-match Rate** | % of rows that matched | Higher = fewer to review |
| **Precision** | Of matched rows, % that were correct | 1.0 = zero false positives |
| **Recall** | Of truly matchable rows, % found | 0.733 = good for risky cases |

**Real Example from Demo:**
- 62.9% auto-matched (confident)
- 1.000 precision (zero false matches)
- 0.733 recall (got 73% of truly matchable pairs)
- 3 unexplained (system refused to guess)

This is **good because:**
- ✅ High precision (no false matches = no audit problems)
- ✅ Explicit "I don't know" (no hidden bad guesses)
- ✅ No claimed 100% match (realistic)

---

#### Threshold Sweep

A chart shows how different "fuzziness levels" affect matching:

```
As threshold increases →
├─ Stricter matching
├─ Fewer auto-matches
└─ More rows → needs_review

As threshold decreases →
├─ Looser matching
├─ More auto-matches
└─ Risk: false positives ⚠️
```

**Our setting (0.90)** is marked on the chart. It balances:
- Matching as many as possible
- Never false-matching (precision = 1.0)

---

## Understanding Exception Codes

### Exception Taxonomy (What Went Wrong?)

| Code | Severity | Meaning | What To Do |
|------|----------|---------|-----------|
| **SETTLEMENT_ONLY** | WARN | In settlement batch, no ledger row | Check if order was cancelled |
| **LEDGER_ONLY** | WARN | In GL, no settlement entry | Check if payment pending |
| **BANK_ONLY** | WARN | In bank statement, no settlement UTR | Check for manual transfer |
| **AMBIGUOUS** | WARN | Multiple possible matches | Choose the most likely manually |
| **FEE_VARIANCE** | WARN | Bridge doesn't close; fee mismatch | Verify MDR rate with Razorpay |
| **RATE_MISMATCH** | CRITICAL | Recorded rate ≠ contracted rate | Escalate to finance; check agreement |
| **INVALID_TDS_CODE** | CRITICAL | TDS code not recognized | Update config/tds_code_map.yaml |
| **TIMING_T_PLUS_N** | WARN | Date beyond tolerance (e.g., T+3) | Normal for delayed settlements |
| **UNEXPLAINED** | INFO | No theory fits; system refused guess | Requires manual investigation |

---

## Common Scenarios & How to Fix Them

### Scenario 1: "FEE_VARIANCE on a Perfect Settlement"

**What You See:**
```
🔴 OPEN -- residual Rs 500.00
Residual attributed to: FEE_VARIANCE -- 
Recorded MDR (2.0%) doesn't match configured rate (2.5%)
```

**Why It Happened:**
- Razorpay changed your MDR mid-month
- MANIFEST is using an old rate in `config/tolerances.yaml`

**How to Fix:**
```bash
# 1. Open: config/tolerances.yaml
settlement_amount_tolerance_percent: 0.01  # 1%
  ↓
# 2. Update the MDR rate:
mdr_rate_percent: 2.5  # Changed from 2.0

# 3. Re-run reconciliation
```

---

### Scenario 2: "SETTLEMENT_ONLY for Order Refunded"

**What You See:**
```
WARN SETTLEMENT_ONLY Rs 2,000.00
Settlement ID: settle_042
Reason: No matching ledger row
```

**Why It Happened:**
- Customer got refund
- Razorpay settlement shows refund
- But your GL doesn't have corresponding refund entry yet

**How to Fix:**
```bash
# Check your GL for this settlement_id
# If found → Add to internal_ledger.csv with negative amount
# If not → Post refund to GL manually

# Then re-upload and re-run
```

---

### Scenario 3: "TIMING_T_PLUS_N (Settlement Delayed)"

**What You See:**
```
WARN TIMING_T_PLUS_N Rs 15,000.00
Settlement dated 2024-01-15 but GL posting 2024-01-18
Date difference: 3 days (exceeds tolerance 2 days)
```

**Why It Happened:**
- Weekend settlement (Fri → Mon posting)
- Bank holiday
- Razorpay batch processing delay

**How to Fix:**
```bash
# This is NORMAL. Check your calendar:
2024-01-15: Monday (settlement date)
2024-01-16-17: Tue-Wed
2024-01-18: Thursday (GL posting date, after Wed/Thu holidays)

# No action needed; acknowledge as timing variance
# Document in audit trail: "Expected T+2, got T+3 due to Diwali"
```

---

### Scenario 4: "UNEXPLAINED Row (Mystery Match)"

**What You See:**
```
INFO UNEXPLAINED
Row IDs: bank_487, settlement_unknown
Reason: No matching theory found after all 6 stages
```

**Why It Happened:**
- Rare case where nothing matches (amount, date, narration)
- Could be:
  - Data entry error
  - Manual transfer mislabeled
  - Settlement from previous month

**How to Fix:**
```bash
# 1. Open the "Ask about this run" section
# 2. Type: "What could cause UNEXPLAINED for row bank_487?"
# 3. AI suggests possible root causes

# 4. Manually investigate:
#    - Search GL for similar amounts
#    - Check if settlement batch header (not individual row)
#    - Verify narration in bank statement

# 5. Once found, update CSVs and re-run
```

---

## FAQ

### Q1: "Why does MANIFEST say there are exceptions when my totals match?"

**Answer:** 
Matching totals is not enough. MANIFEST checks:
- ✅ Totals match (Rs 10,000 in = Rs 10,000 out)
- ✅ Each individual row matched to the right counterpart
- ✅ No row was force-matched to hide a problem

A reconciliation tool that only checks totals would hide:
```
Bank: Row A (Rs 5K) + Row B (Rs 5K) = Rs 10K
Settlement: Row X (Rs 5K) + Row Y (Rs 5K) = Rs 10K

Bad tool: "Totals match! ✓"
MANIFEST: "Row A matched Row Y (wrong!)
           Row B matched Row X (wrong!)
           Exceptions: 2"
```

---

### Q2: "Can I use MANIFEST if I don't have TDS info?"

**Answer:** 
Yes! Leave `tds_section_legacy`, `tds_code_new`, and `tds_amount` blank in your ledger CSV. MANIFEST will skip Stage 4 (TDS validation) for those rows.

```csv
order_id,gross_amount,tds_section_legacy,tds_code_new,tds_amount,vendor_pan_masked,posted_at
"ord_001",50000.00,,,"0.00","XXXXX1234",2024-01-15T12:00:00
                    ↑↑  ↑↑  ↑ (all empty)
```

---

### Q3: "What's the 'Idempotency-Key' error?"

**Answer:** 
This is a safety feature. If you run the same data twice, MANIFEST returns the same result (no duplicate processing).

You don't need to do anything; it's automatic.

---

### Q4: "Can I run MANIFEST without the LLM?"

**Answer:** 
Yes! In the "Run" tab, toggle: **"Use LLM advisory: OFF"**

You'll get:
- ✅ All matches, reviews, and exceptions (same as with LLM)
- ❌ No AI explanations, narratives, or adjustment drafts

LLM is only for explanation; core matching is identical.

---

### Q5: "How do I interpret 'Adjustment Draft'?"

**Answer:**
The AI suggests a GL entry to fix the exception:

```json
{
  "account": "10001",
  "amount": "5000.00",
  "description": "Post-settle reconciling item"
}
```

**This is NOT automatic.** It's a suggestion. You:
1. Review the suggestion
2. Manually post to your GL (or not)
3. Re-run reconciliation next cycle

---

### Q6: "Does MANIFEST delete or modify my data?"

**Answer:** 
**No.** MANIFEST:
- ✅ Reads your CSVs
- ✅ Stores analysis results (in its own DuckDB database)
- ❌ Never modifies your original files
- ❌ Never deletes anything

Your CSVs are safe.

---

### Q7: "Can I download the analysis?"

**Answer:** 
Yes! Three ways:

1. **Export exceptions:** Click "Export filtered exceptions (CSV)" in Manifest tab
2. **View audit trail:** Click "Verify audit chain" at the bottom
3. **Screenshot metrics:** Use your browser's screenshot tool on Metrics tab

---

### Q8: "What if my CSV files have different column names?"

**Answer:** 
MANIFEST expects **exact column names**. If yours are different:

```csv
# Your file:
transaction_date,credit_amount,description

# MANIFEST expects:
txn_date,credit,narration
```

**How to fix:**
Rename columns in your CSV editor (Excel, Google Sheets, etc.) and re-upload.

---

### Q9: "How long does reconciliation take?"

**Answer:** 
Depends on your file sizes:
- **Small (< 1,000 rows):** ~0.5 seconds
- **Medium (10,000 rows):** ~2 seconds
- **Large (50,000 rows):** ~10 seconds

The Streamlit UI shows a live status box so you know it's working.

---

### Q10: "Is my data secure?"

**Answer:** 
Yes:
- ✅ Data stored locally (not sent to cloud servers)
- ✅ DuckDB encrypted at rest
- ✅ Audit log hash-chained (detects tampering)
- ✅ LLM text wrapped in security tags (prevents injection)

For production: Use HTTPS + VPN.

---

## Troubleshooting

### "File upload fails: 'Size too large'"

**Problem:**
```
Error: File size exceeds 10GB limit
```

**Solution:**
```bash
# Check file size:
ls -lh bank_statement.csv

# If > 10GB, split into smaller files (by date range)
# Example: Jan + Feb settlements separately
```

---

### "Upload says 'Too many rows'"

**Problem:**
```
Error: Row count exceeds 50,000 limit
```

**Solution:**
```bash
# Check row count:
wc -l bank_statement.csv

# If > 50,001 rows, split by date:
# Jan-Jun 2024 → separate file
# Jul-Dec 2024 → separate file

# Run MANIFEST twice, then combine results
```

---

### "Reconciliation crashes with 'Invalid date format'"

**Problem:**
```
Error: Could not parse date: "15-Jan-2024"
```

**Solution:**
Your dates must be **ISO format**: `YYYY-MM-DD`

```bash
# Wrong:
15-Jan-2024
1/15/2024
2024/01/15

# Correct:
2024-01-15
```

**Fix in Excel:**
```
Column → Format Cells → Custom → yyyy-mm-dd
```

---

### "Exception says 'Invalid TDS Code'"

**Problem:**
```
CRITICAL INVALID_TDS_CODE
TDS code "195" not in config/tds_code_map.yaml
```

**Solution:**
```bash
# Edit: config/tds_code_map.yaml
# Add the missing code:

section_195:
  legacy: "195"
  new_code: "194O"  # Map to new code
  verified: true    # Mark as verified after checking

# Re-run reconciliation
```

---

### "Metrics tab shows 'Ground truth not available'"

**Problem:**
```
ground_truth_metrics_available: False
```

**Solution:**
This happens when you upload custom data (not demo). MANIFEST can only calculate precision/recall against demo data where ground truth is known.

**This is expected and fine.** Your exceptions are still valid; just no precision score.

---

### "Fuzzy threshold slider has no effect"

**Problem:**
No change in results when moving slider.

**Solution:**
```bash
# Threshold only affects Stage 5 (fuzzy matching)
# If Stage 1 (UTR exact) matches everything, 
# threshold doesn't matter

# To see fuzzy threshold effect:
# Use data with NO UTR matches
# (e.g., settlement batch from external vendor)
```

---

### "LLM answers seem generic"

**Problem:**
```
Assistant: "This could be a timing issue or data entry error.
Check your GL posting dates."
```

**Solution:**
This means no API key is set. MANIFEST falls back to deterministic templates.

To enable real AI:
```bash
# Set environment variable:
export ANTHROPIC_API_KEY="sk-ant-..."

# Or use free NVIDIA API:
export NVIDIA_API_KEY="nvapi-..."

# Restart app:
streamlit run app/streamlit_app.py
```

---

### "Audit chain verification fails"

**Problem:**
```
Error: Audit chain verification FAILED 
-- a record has been tampered with or removed.
```

**Solution:**
This means an audit log entry was edited (security issue).

```bash
# 1. Do NOT ignore this
# 2. Check who has database access
# 3. Contact admin

# In production:
# - Enable database-level audit logs
# - Use read-only replicas for reporting
# - Never allow manual edits to audit table
```

---

## Best Practices

### ✅ Do This

1. **Run reconciliation monthly** (right after settlement close)
2. **Keep exception exports** (for audit trail)
3. **Update config.yaml** when rates change (MDR, TDS codes)
4. **Cross-check large exceptions** (> Rs 1,00,000) with finance team
5. **Document anomalies** (e.g., "Banking holiday T+3 settlement")

---

### ❌ Don't Do This

1. **Ignore UNEXPLAINED rows** (they need investigation)
2. **Force-match exceptions** to claim 100% reconciliation
3. **Modify CSV files after upload** (breaks audit trail)
4. **Use MANIFEST alone** (always have human review)
5. **Skip the Metrics tab** (don't verify accuracy)

---

## Next Steps

### For First-Time Users

```
1. Click "Load demo dataset" (1 min)
   ↓
2. Run reconciliation with defaults (1 min)
   ↓
3. Browse each tab (Bridge, Manifest, Metrics) (5 min)
   ↓
4. Read the exception explanations (5 min)
   ↓
5. Try uploading your own data (10 min)
```

**Total time: ~20 minutes**

---

### For Regular Users

```
Monthly workflow:
1. Export settlement batch from Razorpay
2. Export ledger report from ERP (QuickBooks, SAP, etc.)
3. Get bank statement from bank
4. Upload all 3 to MANIFEST (in Upload tab)
5. Run reconciliation (Run tab)
6. Review exceptions (Manifest tab)
7. Verify bridge waterfall (Bridge tab)
8. Export exception report for auditors
9. Post adjustment entries to GL
10. Re-run next month to verify all cleared
```

---

### For Finance Teams

```
Weekly dashboard:
1. View summary metrics: matched %, exceptions count
2. Filter exceptions by severity
3. Assign exceptions to team members
4. Track via exported CSVs
5. Follow up in next cycle
```

**Pro tip:** Export exceptions → Import to Google Sheets → Share with team for collaborative tracking.

---

## Getting Help

**Still confused?**

1. **Check FAQ above** (most common questions answered)
2. **Try the demo** with different settings
3. **Read exception detail** (includes AI explanation)
4. **Check ARCHITECTURE.md** (technical deep-dive)
5. **Open a GitHub issue** with:
   - What you tried
   - What you expected
   - What happened instead
   - Screenshot + error message

---

## Support

📧 **Questions?** Comment on the GitHub repository  
📚 **Documentation:** See `SYSTEM_ARCHITECTURE.md` and `ARCHITECTURE.md`  
🐛 **Bug Report:** GitHub Issues  
💡 **Feature Request:** GitHub Discussions  

---

## Summary

**MANIFEST is your financial reconciliation assistant that:**

✅ Never claims 100% match (honest reporting)  
✅ Shows exactly what's unmatched (no hidden problems)  
✅ Explains exceptions in plain English (AI-powered)  
✅ Includes audit trail (tamper-proof)  
✅ Works locally (no data leaves your machine)  

**You're ready to go!** 🚀

Start with the demo → Upload your data → Review results → Adjust as needed.

---

**Last Updated:** 2026-09-04  
**Version:** 1.0 (User Guide)
