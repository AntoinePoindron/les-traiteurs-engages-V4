import datetime
from decimal import Decimal

from sqlalchemy import extract, func, select

from models import Quote

CENT = Decimal("0.01")


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
    """Compute all totals from line items, returning Decimals throughout.

    Callers should write Decimal values directly into Numeric columns
    (Quote.total_amount_ht etc.). For storage in the Quote.details JSON
    column (display-only), pass the dict through `totals_for_json`.
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


def totals_for_json(totals):
    """Convert a Decimal-typed totals dict to a JSON-serialisable dict.

    Used when persisting to JSON columns for display purposes only.
    Callers should NOT round-trip business calculations through this.
    """
    def conv(v):
        if isinstance(v, Decimal):
            return float(v)
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        return v
    return {k: conv(v) for k, v in totals.items()}
