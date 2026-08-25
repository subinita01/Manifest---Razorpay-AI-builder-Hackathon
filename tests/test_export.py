from decimal import Decimal

from backend.export import exceptions_to_csv


def test_exceptions_to_csv_includes_header_and_rows():
    exceptions = [
        {
            "exception_id": "exc1",
            "taxonomy_code": "BANK_ONLY",
            "severity": "WARN",
            "row_ids": ["3"],
            "amount_impact": Decimal("500.00"),
            "detail": {"narration": "NEFT CR-TEST"},
        }
    ]
    csv_text = exceptions_to_csv(exceptions)
    assert "exception_id,taxonomy_code,severity,row_ids,amount_impact,detail" in csv_text
    assert "BANK_ONLY" in csv_text


def test_exceptions_to_csv_neutralises_formula_injection_in_every_text_field():
    # The actual injection risk is Excel treating a cell as a formula
    # because it *starts with* =/+/-/@; the neutralized value legitimately
    # still contains the original payload as a substring once quote-
    # prefixed, so the property to check is "never starts with it raw",
    # not "never appears anywhere".
    payload = "=cmd|'/c calc'!A1"
    exceptions = [
        {
            "exception_id": payload,
            "taxonomy_code": "BANK_ONLY",
            "severity": "WARN",
            "row_ids": ["3"],
            "amount_impact": Decimal("500.00"),
            "detail": {"narration": payload},
        }
    ]
    csv_text = exceptions_to_csv(exceptions)
    assert "'" + payload in csv_text

    import csv
    import io

    rows = list(csv.reader(io.StringIO(csv_text)))
    for field in rows[1]:  # the one data row, properly split respecting quoting
        assert not field.startswith(("=", "+", "-", "@")), field
