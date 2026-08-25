from decimal import Decimal

import pytest

from core.config import UnknownTDSCodeError, lookup_new_code, lookup_rate


def test_lookup_new_code_for_known_legacy_section():
    entry = lookup_new_code("194J")
    assert entry.new_code == "1026"
    assert entry.verified is False


def test_lookup_new_code_raises_on_unknown_section():
    with pytest.raises(UnknownTDSCodeError):
        lookup_new_code("999Z")


def test_lookup_rate_for_known_code():
    rate = lookup_rate("1026")
    assert rate.rate_with_pan == Decimal("0.10")


def test_lookup_rate_raises_on_unknown_code():
    with pytest.raises(UnknownTDSCodeError):
        lookup_rate("9999")
