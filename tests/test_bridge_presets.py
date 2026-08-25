from app.bridge_presets import pick_clean_default, pick_unresolved_preset


def _utr(settlement_utr, closed, attribution_rule=None, rate_variance_rule=None):
    return {
        "settlement_utr": settlement_utr,
        "closed": closed,
        "attribution_rule": attribution_rule,
        "rate_variance_rule": rate_variance_rule,
    }


def test_clean_default_prefers_closed_with_no_findings():
    utrs = [
        _utr("open1", closed=False, attribution_rule="UNATTRIBUTED"),
        _utr("closed_flagged", closed=True, rate_variance_rule="FEE_VARIANCE"),
        _utr("closed_clean", closed=True),
    ]
    assert pick_clean_default(utrs) == "closed_clean"


def test_clean_default_falls_back_to_any_closed_if_none_are_fully_clean():
    utrs = [
        _utr("open1", closed=False, attribution_rule="UNATTRIBUTED"),
        _utr("closed_flagged", closed=True, rate_variance_rule="FEE_VARIANCE"),
    ]
    assert pick_clean_default(utrs) == "closed_flagged"


def test_clean_default_falls_back_to_first_when_nothing_closes():
    utrs = [_utr("open1", closed=False), _utr("open2", closed=False)]
    assert pick_clean_default(utrs) == "open1"


def test_clean_default_none_when_empty():
    assert pick_clean_default([]) is None


def test_unresolved_preset_prefers_a_genuinely_open_bridge():
    utrs = [
        _utr("closed_clean", closed=True),
        _utr("open1", closed=False, attribution_rule="UNATTRIBUTED"),
    ]
    assert pick_unresolved_preset(utrs) == "open1"


def test_unresolved_preset_falls_back_to_rate_variance_when_everything_closes():
    utrs = [
        _utr("closed_clean", closed=True),
        _utr("closed_flagged", closed=True, rate_variance_rule="FEE_VARIANCE"),
    ]
    assert pick_unresolved_preset(utrs) == "closed_flagged"


def test_unresolved_preset_none_when_nothing_flagged():
    utrs = [_utr("closed_clean", closed=True)]
    assert pick_unresolved_preset(utrs) is None
