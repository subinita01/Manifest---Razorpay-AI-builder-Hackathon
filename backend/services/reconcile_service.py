from __future__ import annotations

from typing import Any

from core.reconciliation.engine import DeterministicReconEngine


class ReconcileService:
    def __init__(self) -> None:
        self.engine = DeterministicReconEngine()

    def run_synthetic_check(self) -> dict[str, Any]:
        sample_bank_rows = [
            {
                "narration": "NEFT CR-RAZORPAY SOFTWARE-UTR2026081412345-STL",
                "credit": "418332.17",
                "txn_date": "2026-08-14",
            },
            {
                "narration": "BANK CREDIT -- NO MATCH",
                "credit": "25000.00",
                "txn_date": "2026-08-14",
            },
        ]
        sample_settlement_rows = [
            {
                "settlement_utr": "2026081412345",
                "amount": "418332.17",
                "fee": "12500.00",
                "tax": "2250.00",
                "order_id": "ord_001",
            },
            {
                "settlement_utr": "2026081412346",
                "amount": "25000.00",
                "fee": "750.00",
                "tax": "135.00",
                "order_id": "ord_002",
            },
        ]
        ledger_rows = [
            {
                "order_id": "ord_001",
                "gross_amount": "418332.17",
                "tds_section_legacy": "194J",
                "tds_code_new": "1026",
                "tds_amount": "10000.00",
                "posted_at": "2026-04-15T00:00:00",
            },
            {
                "order_id": "ord_002",
                "gross_amount": "25000.00",
                "tds_section_legacy": "194C",
                "tds_code_new": "1023",
                "tds_amount": "550.00",
                "posted_at": "2026-04-20T00:00:00",
            },
        ]

        result = self.engine.run_pipeline(
            sample_bank_rows, sample_settlement_rows, ledger_rows, fuzzy_threshold=0.90
        )
        return {
            "status": "ok",
            "stages": [stage["name"] for stage in result["stages"]],
            "matched_rows": len(sample_settlement_rows),
            "exceptions": result["exceptions"],
            "stage_summary": result["stages"],
        }
