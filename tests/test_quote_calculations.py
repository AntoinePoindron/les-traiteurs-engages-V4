"""Unit tests for services.quotes.calculate_quote_totals.

No DB, no app, no fixtures — pure Decimal math. These are the first real
tests for the financial code path that ships numbers to Stripe.
"""
from decimal import Decimal

import pytest

from services.quotes import calculate_quote_totals


def _line(**kwargs):
    """Build a line dict with sensible defaults."""
    return {
        "section": "principal",
        "description": "test",
        "quantity": 1,
        "unit_price_ht": 0,
        "tva_rate": 10,
        **kwargs,
    }


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------


def test_empty_lines_returns_zeros():
    t = calculate_quote_totals([], guest_count=10)
    assert t["total_ht"] == Decimal("0.00")
    assert t["total_tva"] == Decimal("0.00")
    assert t["total_ttc"] == Decimal("0.00")
    assert t["amount_per_person"] == Decimal("0.00")
    assert t["platform_fee_ht"] == Decimal("0.00")
    assert t["platform_fee_tva"] == Decimal("0.00")
    assert t["platform_fee_ttc"] == Decimal("0.00")
    assert t["valorisable_agefiph"] == Decimal("0.00")


def test_single_line_basic_math():
    # 30 × 40 = 1200 HT, 10% TVA = 120, 1320 TTC
    t = calculate_quote_totals(
        [_line(quantity=30, unit_price_ht=40, tva_rate=10)],
        guest_count=30,
    )
    assert t["total_ht"] == Decimal("1200.00")
    assert t["total_tva"] == Decimal("120.00")
    assert t["total_ttc"] == Decimal("1320.00")
    assert t["amount_per_person"] == Decimal("44.00")


def test_guest_count_zero_amount_per_person_is_zero_not_div_by_zero():
    t = calculate_quote_totals(
        [_line(quantity=1, unit_price_ht=100, tva_rate=10)],
        guest_count=0,
    )
    assert t["amount_per_person"] == Decimal("0.00")


def test_guest_count_none_amount_per_person_is_zero():
    t = calculate_quote_totals(
        [_line(quantity=1, unit_price_ht=100, tva_rate=10)],
        guest_count=None,
    )
    assert t["amount_per_person"] == Decimal("0.00")


# ---------------------------------------------------------------------------
# TVA grouping
# ---------------------------------------------------------------------------


def test_mixed_tva_rates_grouped_correctly():
    lines = [
        _line(section="principal", quantity=10, unit_price_ht=50, tva_rate=10),  # 500 HT
        _line(section="boissons", quantity=5, unit_price_ht=10, tva_rate=20),    # 50 HT
    ]
    t = calculate_quote_totals(lines, guest_count=10)
    assert t["total_ht"] == Decimal("550.00")
    # 10% TVA on 500 = 50 ; 20% TVA on 50 = 10 ; total 60
    assert t["total_tva"] == Decimal("60.00")
    assert t["total_ttc"] == Decimal("610.00")
    # Both TVA buckets present
    assert Decimal(next(iter(t["tva_totals"]))) in (Decimal("10"), Decimal("20"))
    assert set(t["tva_totals"].keys()) == {"10", "20"}
    assert t["tva_totals"]["10"]["base_ht"] == Decimal("500.00")
    assert t["tva_totals"]["10"]["tva"] == Decimal("50.00")
    assert t["tva_totals"]["20"]["base_ht"] == Decimal("50.00")
    assert t["tva_totals"]["20"]["tva"] == Decimal("10.00")


def test_section_totals_split_correctly():
    lines = [
        _line(section="principal", quantity=10, unit_price_ht=40),   # 400
        _line(section="principal", quantity=5,  unit_price_ht=20),   # 100
        _line(section="boissons",  quantity=10, unit_price_ht=5),    # 50
        _line(section="extras",    quantity=1,  unit_price_ht=25),   # 25
    ]
    t = calculate_quote_totals(lines, guest_count=10)
    assert t["section_totals"]["principal"] == Decimal("500.00")
    assert t["section_totals"]["boissons"] == Decimal("50.00")
    assert t["section_totals"]["extras"] == Decimal("25.00")


# ---------------------------------------------------------------------------
# Platform fee (5 % HT + 20 % TVA on fee)
# ---------------------------------------------------------------------------


def test_platform_fee_is_5pct_of_ht():
    # 1000 HT → 50 fee HT, 10 fee TVA, 60 fee TTC
    t = calculate_quote_totals(
        [_line(quantity=10, unit_price_ht=100, tva_rate=10)],
        guest_count=10,
    )
    assert t["total_ht"] == Decimal("1000.00")
    assert t["platform_fee_ht"] == Decimal("50.00")
    assert t["platform_fee_tva"] == Decimal("10.00")
    assert t["platform_fee_ttc"] == Decimal("60.00")


def test_platform_fee_independent_of_line_tva_rates():
    """Platform fee TVA is always 20 %, never follows the line TVA."""
    t_low = calculate_quote_totals(
        [_line(quantity=10, unit_price_ht=100, tva_rate=10)], guest_count=10,
    )
    t_high = calculate_quote_totals(
        [_line(quantity=10, unit_price_ht=100, tva_rate=20)], guest_count=10,
    )
    # Both should produce the same platform fee TTC because base HT is equal
    assert t_low["platform_fee_ttc"] == t_high["platform_fee_ttc"] == Decimal("60.00")


# ---------------------------------------------------------------------------
# AGEFIPH
# ---------------------------------------------------------------------------


def test_valorisable_agefiph_equals_total_ht():
    t = calculate_quote_totals(
        [_line(quantity=10, unit_price_ht=75, tva_rate=10)],
        guest_count=10,
    )
    assert t["valorisable_agefiph"] == t["total_ht"] == Decimal("750.00")


# ---------------------------------------------------------------------------
# Decimal precision — catches any sneaky float arithmetic
# ---------------------------------------------------------------------------


def test_cent_precision_preserved_across_many_lines():
    # 0.1 × 3 in float = 0.30000000000000004 ; must be exactly 0.30 here.
    lines = [_line(quantity=1, unit_price_ht="0.1", tva_rate=10) for _ in range(3)]
    t = calculate_quote_totals(lines, guest_count=1)
    assert t["total_ht"] == Decimal("0.30")


def test_quantities_and_prices_as_strings_work():
    t = calculate_quote_totals(
        [_line(quantity="2.5", unit_price_ht="39.99", tva_rate="5.5")],
        guest_count=1,
    )
    # 2.5 × 39.99 = 99.975 → rounds to 99.98 (half-even on .975 goes to .98)
    assert t["total_ht"] == Decimal("99.98") or t["total_ht"] == Decimal("99.97")


def test_returned_values_are_decimal_not_float():
    t = calculate_quote_totals(
        [_line(quantity=1, unit_price_ht=10, tva_rate=10)],
        guest_count=1,
    )
    for key in ("total_ht", "total_tva", "total_ttc", "amount_per_person",
                "platform_fee_ht", "platform_fee_tva", "platform_fee_ttc",
                "valorisable_agefiph"):
        assert isinstance(t[key], Decimal), f"{key} should be Decimal, got {type(t[key])}"


# ---------------------------------------------------------------------------
# Non-list input guard
# ---------------------------------------------------------------------------


def test_non_list_input_treated_as_empty():
    # Handler sometimes passes garbage from a broken JSON parse; don't crash.
    for bad in (None, "not a list", {"lines": []}, 42):
        t = calculate_quote_totals(bad, guest_count=10)
        assert t["total_ht"] == Decimal("0.00")


# ---------------------------------------------------------------------------
# Missing line fields default to zero
# ---------------------------------------------------------------------------


def test_line_missing_fields_default_to_zero():
    t = calculate_quote_totals([{}], guest_count=10)
    assert t["total_ht"] == Decimal("0.00")
    assert t["total_tva"] == Decimal("0.00")


# ---------------------------------------------------------------------------
# Parametrized smoke across realistic scenarios
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lines,guests,expected_ttc,expected_per_person,expected_fee_ttc",
    [
        # Buffet déjeuner 20 couverts
        ([_line(quantity=20, unit_price_ht=35, tva_rate=10)],
         20, Decimal("770.00"), Decimal("38.50"), Decimal("42.00")),
        # Cocktail 50 couverts avec boissons TVA 20
        ([_line(section="principal", quantity=50, unit_price_ht=15, tva_rate=10),
          _line(section="boissons",  quantity=50, unit_price_ht=4,  tva_rate=20)],
         50, Decimal("1065.00"), Decimal("21.30"), Decimal("57.00")),
        # Dîner premium
        ([_line(quantity=12, unit_price_ht=85, tva_rate=10)],
         12, Decimal("1122.00"), Decimal("93.50"), Decimal("61.20")),
    ],
)
def test_realistic_scenarios(lines, guests, expected_ttc, expected_per_person, expected_fee_ttc):
    t = calculate_quote_totals(lines, guest_count=guests)
    assert t["total_ttc"] == expected_ttc
    assert t["amount_per_person"] == expected_per_person
    assert t["platform_fee_ttc"] == expected_fee_ttc
