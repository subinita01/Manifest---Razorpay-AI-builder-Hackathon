from core.taxonomy import TAXONOMY, ExceptionCode, Severity


def test_every_exception_code_has_a_taxonomy_entry():
    for code in ExceptionCode:
        assert code in TAXONOMY, code


def test_every_entry_has_a_valid_severity_and_nonempty_template():
    for entry in TAXONOMY.values():
        assert entry.severity in Severity
        assert entry.resolution_template.strip() != ""


def test_needs_review_is_not_a_taxonomy_code():
    assert not hasattr(ExceptionCode, "NEEDS_REVIEW")
