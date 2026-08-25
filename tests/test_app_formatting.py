from decimal import Decimal

from app.formatting import format_int, format_money, format_pct


def test_format_money_adds_thousands_separator_and_two_decimals():
    assert format_money(Decimal("452180")) == "452,180.00"
    assert format_money(Decimal("1234.5")) == "1,234.50"
    assert format_money(None) == "-"


def test_format_pct():
    assert format_pct(0.629) == "62.9%"
    assert format_pct(1.0) == "100.0%"


def test_format_int_adds_thousands_separator():
    assert format_int(1269) == "1,269"
