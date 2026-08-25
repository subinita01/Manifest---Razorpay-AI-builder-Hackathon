from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.models import BRIDGE_TOLERANCE, TOLERANCE, BankRow


def _bank_row_kwargs(**overrides):
    kwargs = dict(
        txn_date="2026-08-14",
        narration="NEFT CR-RAZORPAY SOFTWARE-UTR2026081412345-STL",
        debit="0",
        credit="1000.00",
        balance="2000000.00",
    )
    kwargs.update(overrides)
    return kwargs


def test_money_field_rejects_float():
    with pytest.raises(ValidationError):
        BankRow(**_bank_row_kwargs(credit=1000.00))


def test_money_field_parses_string_to_exact_decimal():
    row = BankRow(**_bank_row_kwargs(credit="1234.56"))
    assert row.credit == Decimal("1234.56")


def test_extra_columns_are_rejected():
    with pytest.raises(ValidationError):
        BankRow(**_bank_row_kwargs(unexpected_column="oops"))


def test_tolerance_constants_are_decimal():
    assert TOLERANCE == Decimal("0.01")
    assert BRIDGE_TOLERANCE == Decimal("1.00")
