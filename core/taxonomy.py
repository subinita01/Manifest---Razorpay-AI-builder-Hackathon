"""Exception taxonomy for MANIFEST.

PRODUCT_SPEC.md is not present in this repository, so this taxonomy is
derived directly from what the matching cascade (core/matching/) actually
produces, rather than copied from an external spec. Every code here
corresponds to a real finding some stage can emit; none are aspirational.

NEEDS_REVIEW is deliberately not a taxonomy code: it's a top-level pipeline
bucket (see core/pipeline.py's invariant, matched + needs_review +
exceptions == total_input_rows), not an exception classification.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


class ExceptionCode(str, Enum):
    BANK_ONLY = "BANK_ONLY"
    LEDGER_ONLY = "LEDGER_ONLY"
    SETTLEMENT_ONLY = "SETTLEMENT_ONLY"
    FEE_VARIANCE = "FEE_VARIANCE"
    GST_ON_MDR_VARIANCE = "GST_ON_MDR_VARIANCE"
    ROUNDING = "ROUNDING"
    TDS_CODE_MIGRATION_BREAK = "TDS_CODE_MIGRATION_BREAK"
    TDS_RATE_MISMATCH = "TDS_RATE_MISMATCH"
    TDS_AMOUNT_MISMATCH = "TDS_AMOUNT_MISMATCH"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
    UNEXPLAINED = "UNEXPLAINED"


@dataclass(frozen=True)
class TaxonomyEntry:
    severity: Severity
    resolution_template: str


TAXONOMY: dict[ExceptionCode, TaxonomyEntry] = {
    ExceptionCode.BANK_ONLY: TaxonomyEntry(
        Severity.WARN,
        "Investigate bank credit {bank_row_id}: no settlement batch or order explains it.",
    ),
    ExceptionCode.LEDGER_ONLY: TaxonomyEntry(
        Severity.WARN,
        "Order {order_id} was posted to the ledger but never appears in a settlement batch.",
    ),
    ExceptionCode.SETTLEMENT_ONLY: TaxonomyEntry(
        Severity.WARN,
        "Settlement row {settlement_id} has no matching ledger entry.",
    ),
    ExceptionCode.FEE_VARIANCE: TaxonomyEntry(
        Severity.WARN,
        "MDR charged at {implied_rate} against a contracted {contracted_rate} "
        "on UTR {settlement_utr}.",
    ),
    ExceptionCode.GST_ON_MDR_VARIANCE: TaxonomyEntry(
        Severity.WARN,
        "GST on MDR charged at {implied_rate} against a contracted {contracted_rate} "
        "on UTR {settlement_utr}.",
    ),
    ExceptionCode.ROUNDING: TaxonomyEntry(
        Severity.INFO,
        "Residual of {residual} on UTR {settlement_utr} is within sub-rupee tolerance.",
    ),
    ExceptionCode.TDS_CODE_MIGRATION_BREAK: TaxonomyEntry(
        Severity.CRITICAL,
        "Order {order_id}'s TDS code is missing or contradicts "
        "config/tds_code_map.yaml (unverified -- confirm against the CBDT "
        "notification before filing).",
    ),
    ExceptionCode.TDS_RATE_MISMATCH: TaxonomyEntry(
        Severity.WARN,
        "Order {order_id}'s implied TDS rate does not match the scheduled rate for its code.",
    ),
    ExceptionCode.TDS_AMOUNT_MISMATCH: TaxonomyEntry(
        Severity.WARN,
        "Order {order_id}'s deducted TDS of {actual_tds} differs from the "
        "expected {expected_tds}.",
    ),
    ExceptionCode.AMBIGUOUS_MATCH: TaxonomyEntry(
        Severity.WARN,
        "Two or more candidates scored within the ambiguity margin; resolve manually.",
    ),
    ExceptionCode.UNEXPLAINED: TaxonomyEntry(
        Severity.CRITICAL,
        "No stage in the cascade could explain this record. Manual investigation required.",
    ),
}
