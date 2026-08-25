"""Load raw bank/settlement/ledger CSVs into the typed row dicts the
matching cascade (core/matching/) expects.

This is parsing only -- no network calls, no env secrets -- so it lives in
core/ alongside normalize.py rather than in backend/ or scripts/.
"""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
from typing import Any

from core.normalize import parse_date, parse_money


def load_bank_csv(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open() as f:
        for i, r in enumerate(csv.DictReader(f)):
            rows.append(
                {
                    "row_id": i,
                    "narration": r["narration"],
                    "credit": parse_money(r["credit"]),
                    "txn_date": parse_date(r["txn_date"]),
                    "ref_no": r.get("ref_no") or None,
                }
            )
    return rows


def load_settlement_csv(path: Path) -> list[dict[str, Any]]:
    from datetime import datetime

    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            rows.append(
                {
                    "settlement_id": r["settlement_id"],
                    "settlement_utr": r["settlement_utr"],
                    "amount": Decimal(r["amount"]),
                    "fee": Decimal(r["fee"]),
                    "tax": Decimal(r["tax"]),
                    "on_hold": r["on_hold"] == "True",
                    "type": r["type"],
                    "settled_at": datetime.fromisoformat(r["settled_at"]),
                    "order_id": r["order_id"] or None,
                    "dispute_id": r["dispute_id"] or None,
                }
            )
    return rows


def load_ledger_csv(path: Path) -> list[dict[str, Any]]:
    from datetime import datetime

    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            rows.append(
                {
                    "order_id": r["order_id"],
                    "gross_amount": Decimal(r["gross_amount"]),
                    "tds_section_legacy": r["tds_section_legacy"] or None,
                    "tds_code_new": r["tds_code_new"] or None,
                    "tds_amount": Decimal(r["tds_amount"]),
                    "vendor_pan_masked": r["vendor_pan_masked"],
                    "posted_at": datetime.fromisoformat(r["posted_at"]),
                }
            )
    return rows
