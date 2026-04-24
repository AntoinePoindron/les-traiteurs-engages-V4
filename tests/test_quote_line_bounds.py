"""Audit finding #10: quote line inputs must be bounded.

`services/quotes.py::lines_from_dicts` runs every value through
`Decimal(str(...))` with no bounds. Callers (notably the caterer quote
editor) can pass:
    - negative unit_price_ht           → Stripe will reject at invoice time
    - quantity outside plausible range → silent data corruption
    - tva_rate that is not a legal FR rate
    - fields that are not numeric at all (NaN/inf)

This test locks in the rule: such inputs must ValueError at parse time
rather than silently flowing into the DB or Stripe.
"""
from decimal import Decimal

import pytest


LEGAL_TVA = {Decimal("0"), Decimal("2.1"), Decimal("5.5"), Decimal("10"), Decimal("20")}


def test_negative_unit_price_is_rejected():
    from services.quotes import lines_from_dicts

    with pytest.raises(ValueError):
        lines_from_dicts([{
            "section": "principal", "description": "x",
            "quantity": 1, "unit_price_ht": -10, "tva_rate": 10,
        }])


def test_negative_quantity_is_rejected():
    from services.quotes import lines_from_dicts

    with pytest.raises(ValueError):
        lines_from_dicts([{
            "section": "principal", "description": "x",
            "quantity": -1, "unit_price_ht": 10, "tva_rate": 10,
        }])


def test_illegal_tva_rate_is_rejected():
    from services.quotes import lines_from_dicts

    with pytest.raises(ValueError):
        lines_from_dicts([{
            "section": "principal", "description": "x",
            "quantity": 1, "unit_price_ht": 10, "tva_rate": 42,
        }])


def test_non_numeric_value_is_rejected():
    from services.quotes import lines_from_dicts

    with pytest.raises(ValueError):
        lines_from_dicts([{
            "section": "principal", "description": "x",
            "quantity": "NaN", "unit_price_ht": 10, "tva_rate": 10,
        }])


def test_valid_line_still_parses():
    """Regression guard — don't break the happy path."""
    from services.quotes import lines_from_dicts

    lines = lines_from_dicts([{
        "section": "principal", "description": "plateau",
        "quantity": 20, "unit_price_ht": "12.50", "tva_rate": "10",
    }])
    assert len(lines) == 1
    assert lines[0].quantity == Decimal("20")
    assert lines[0].unit_price_ht == Decimal("12.50")
    assert lines[0].tva_rate == Decimal("10")
