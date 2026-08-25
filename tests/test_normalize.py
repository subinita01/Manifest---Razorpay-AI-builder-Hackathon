from datetime import date
from decimal import Decimal

import pytest

from core.normalize import (
    UnparseableDate,
    extract_utr,
    normalize_narration,
    parse_date,
    parse_money,
    sanitize_cell,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-08-14", date(2026, 8, 14)),
        ("14/08/2026", date(2026, 8, 14)),
        ("14-Aug-26", date(2026, 8, 14)),
    ],
)
def test_parse_date_handles_known_formats(raw, expected):
    assert parse_date(raw) == expected


def test_parse_date_raises_on_unknown_format():
    with pytest.raises(UnparseableDate):
        parse_date("August 14, 2026")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1,234.56", Decimal("1234.56")),
        ("(123.45)", Decimal("-123.45")),
        ("", None),
        (None, None),
        ("100.00", Decimal("100.00")),
    ],
)
def test_parse_money(raw, expected):
    assert parse_money(raw) == expected


@pytest.mark.parametrize(
    "narration,expected",
    [
        ("NEFT CR-RAZORPAY SOFTWARE PVT LTD-UTR2026081412345-STL", "2026081412345"),
        ("RTGS/2545738757177514/RAZORPAY/SETTLEMENT", "2545738757177514"),
        ("UPI-SETTLEMENT-6617979688680589", "6617979688680589"),
    ],
)
def test_extract_utr_from_known_narration_formats(narration, expected):
    assert extract_utr(narration) == expected


def test_extract_utr_returns_none_on_miss():
    assert extract_utr("MISC BANK CHARGES") is None


def test_extract_utr_returns_none_when_utr_too_short():
    assert extract_utr("NEFT CR-RAZORPAY SOFTWARE PVT LTD-UTR202608-STL") is None


def test_normalize_narration_uppercases_collapses_and_strips_punctuation():
    assert normalize_narration("  neft cr - razorpay!!  software  ") == "NEFT CR RAZORPAY SOFTWARE"


def test_sanitize_cell_neutralises_formula_injection_payload():
    payload = "=cmd|'/c calc'!A1"
    sanitized = sanitize_cell(payload)
    assert sanitized == "'" + payload
    assert not sanitized.startswith("=")


def test_sanitize_cell_leaves_normal_text_untouched():
    assert sanitize_cell("NEFT CR-RAZORPAY") == "NEFT CR-RAZORPAY"
