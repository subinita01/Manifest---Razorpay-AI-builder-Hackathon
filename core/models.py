"""Domain models for MANIFEST. All money is Decimal, never float."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

TOLERANCE = Decimal("0.01")
BRIDGE_TOLERANCE = Decimal("1.00")


def _to_decimal(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("float is not an accepted type for money fields; use str or Decimal")
    if isinstance(value, str):
        return Decimal(value)
    return value


def _to_date(value: Any) -> Any:
    if isinstance(value, str):
        return date.fromisoformat(value)
    return value


def _to_datetime(value: Any) -> Any:
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


MoneyDecimal = Annotated[Decimal, BeforeValidator(_to_decimal)]
StrictDate = Annotated[date, BeforeValidator(_to_date)]
StrictDatetime = Annotated[datetime, BeforeValidator(_to_datetime)]


class BankRow(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    txn_date: StrictDate
    value_date: StrictDate | None = None
    narration: str
    ref_no: str | None = None
    debit: MoneyDecimal
    credit: MoneyDecimal
    balance: MoneyDecimal


class SettlementRow(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    settlement_id: str
    settlement_utr: str
    entity_id: str
    type: str
    amount: MoneyDecimal
    fee: MoneyDecimal
    tax: MoneyDecimal
    on_hold: bool
    settled: bool
    created_at: StrictDatetime
    settled_at: StrictDatetime | None = None
    payment_id: str | None = None
    order_id: str | None = None
    dispute_id: str | None = None
    method: str | None = None
    card_network: str | None = None


class LedgerRow(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    order_id: str
    invoice_no: str
    gross_amount: MoneyDecimal
    tds_section_legacy: str | None = None
    tds_code_new: str | None = None
    tds_amount: MoneyDecimal
    gst_rate: MoneyDecimal
    vendor_pan_masked: str
    posted_at: StrictDatetime


class MatchResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    match_id: str
    stage_name: str
    bank_row_id: str | None = None
    settlement_row_id: str | None = None
    ledger_row_id: str | None = None
    confidence: float = 1.0
    detail: dict[str, Any] = Field(default_factory=dict)


class Exception_(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    exception_id: str
    taxonomy_code: str
    severity: str
    row_ids: list[str] = Field(default_factory=list)
    amount_impact: MoneyDecimal = Decimal("0")
    detail: dict[str, Any] = Field(default_factory=dict)


class RunManifest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", protected_namespaces=())

    run_id: str
    seed: int
    git_sha: str | None = None
    config_hash: str
    model_string: str | None = None
    library_versions: dict[str, str] = Field(default_factory=dict)
    created_at: StrictDatetime
