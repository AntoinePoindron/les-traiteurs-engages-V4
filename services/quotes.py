import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import extract, func, select

from models import Quote, QuoteLine

CENT = Decimal("0.01")

# Legal FR VAT rates. Anything else is either a typo or an attempt to
# corrupt the ledger. Audit finding #10 (2026-04-24).
LEGAL_TVA_RATES: frozenset[Decimal] = frozenset(
    {Decimal("0"), Decimal("2.1"), Decimal("5.5"), Decimal("10"), Decimal("20")}
)
# Plausible caps — enough for the largest real caterer quotes, small
# enough to catch malicious input before it reaches Stripe.
MAX_QUANTITY = Decimal("10000")
MAX_UNIT_PRICE_HT = Decimal("100000")


def _parse_finite_decimal(raw, field: str) -> Decimal:
    """Convert raw input to a finite Decimal or raise ValueError."""
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"{field}: not a number ({raw!r})") from exc
    if not value.is_finite():
        raise ValueError(f"{field}: must be finite, got {value}")
    return value


def lines_from_dicts(line_dicts: list[dict]) -> list[QuoteLine]:
    """Parse + validate quote line dicts into QuoteLine rows.

    Raises ValueError on any out-of-range or non-numeric input. Callers
    in `blueprints/caterer.py` catch this and surface a form error rather
    than silently writing bad data into the DB or the Stripe invoice.
    """
    result: list[QuoteLine] = []
    for i, d in enumerate(line_dicts):
        quantity = _parse_finite_decimal(d.get("quantity", 0), f"line {i} quantity")
        unit_price_ht = _parse_finite_decimal(
            d.get("unit_price_ht", 0), f"line {i} unit_price_ht"
        )
        tva_rate = _parse_finite_decimal(d.get("tva_rate", 10), f"line {i} tva_rate")

        if quantity < 0 or quantity > MAX_QUANTITY:
            raise ValueError(f"line {i}: quantity out of range ({quantity})")
        if unit_price_ht < 0 or unit_price_ht > MAX_UNIT_PRICE_HT:
            raise ValueError(f"line {i}: unit_price_ht out of range ({unit_price_ht})")
        if tva_rate not in LEGAL_TVA_RATES:
            raise ValueError(f"line {i}: tva_rate {tva_rate} not in {sorted(LEGAL_TVA_RATES)}")

        result.append(QuoteLine(
            position=i,
            section=str(d.get("section") or "principal")[:50],
            description=d.get("description") or None,
            quantity=quantity,
            unit_price_ht=unit_price_ht,
            tva_rate=tva_rate,
        ))
    return result


def line_to_dict(line: QuoteLine) -> dict:
    return {
        "section": line.section,
        "description": line.description or "",
        "quantity": float(line.quantity),
        "unit_price_ht": float(line.unit_price_ht),
        "tva_rate": float(line.tva_rate),
    }


def generate_quote_reference(session, caterer):
    """Generate DEVIS-{invoice_prefix}-YYYY-NNN sequential per caterer per year."""
    year = datetime.date.today().year
    count = session.scalar(
        select(func.count(Quote.id))
        .where(Quote.caterer_id == caterer.id)
        .where(extract("year", Quote.created_at) == year)
    )
    return f"DEVIS-{caterer.invoice_prefix}-{year}-{count + 1:03d}"


def derive_invoice_reference(quote_reference):
    """Convert DEVIS-XXX to FAC-XXX."""
    return quote_reference.replace("DEVIS-", "FAC-", 1)


def calculate_quote_totals(details, guest_count):
    """Compute all totals from line items as Decimals.

    Callers write the relevant fields onto Quote columns
    (`total_amount_ht`, `amount_per_person`, `valorisable_agefiph`).
    Templates that need richer breakdowns (per-section, per-TVA-rate) call
    this helper at render time — there is no persisted cache.
    """
    lines = details if isinstance(details, list) else []

    section_totals: dict[str, Decimal] = {}
    tva_totals: dict[str, dict[str, Decimal]] = {}
    total_ht = Decimal("0")
    total_tva = Decimal("0")

    for line in lines:
        qty = Decimal(str(line.get("quantity", 0)))
        unit_price = Decimal(str(line.get("unit_price_ht", 0)))
        tva_rate = Decimal(str(line.get("tva_rate", 10)))
        section = line.get("section", "principal")

        line_ht = qty * unit_price
        line_tva = line_ht * tva_rate / Decimal("100")

        total_ht += line_ht
        total_tva += line_tva

        section_totals[section] = section_totals.get(section, Decimal("0")) + line_ht

        tva_key = str(tva_rate)
        if tva_key not in tva_totals:
            tva_totals[tva_key] = {"base_ht": Decimal("0"), "tva": Decimal("0")}
        tva_totals[tva_key]["base_ht"] += line_ht
        tva_totals[tva_key]["tva"] += line_tva

    total_ttc = total_ht + total_tva

    # Platform fee: 5% of total_ht, TVA 20% on fee
    platform_fee_ht = total_ht * Decimal("0.05")
    platform_fee_tva = platform_fee_ht * Decimal("0.20")
    platform_fee_ttc = platform_fee_ht + platform_fee_tva

    amount_per_person = total_ttc / Decimal(str(guest_count)) if guest_count else Decimal("0")

    # AGEFIPH: total HT is valorisable for ESAT/EA structures
    valorisable_agefiph = total_ht

    return {
        "section_totals": {k: v.quantize(CENT) for k, v in section_totals.items()},
        "tva_totals": {
            k: {"base_ht": v["base_ht"].quantize(CENT), "tva": v["tva"].quantize(CENT)}
            for k, v in tva_totals.items()
        },
        "total_ht": total_ht.quantize(CENT),
        "total_tva": total_tva.quantize(CENT),
        "total_ttc": total_ttc.quantize(CENT),
        "amount_per_person": amount_per_person.quantize(CENT),
        "platform_fee_ht": platform_fee_ht.quantize(CENT),
        "platform_fee_tva": platform_fee_tva.quantize(CENT),
        "platform_fee_ttc": platform_fee_ttc.quantize(CENT),
        "valorisable_agefiph": valorisable_agefiph.quantize(CENT),
    }
