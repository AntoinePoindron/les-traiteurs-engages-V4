import datetime
from decimal import Decimal

from sqlalchemy import extract, func, select

from models import Quote


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
    """Compute all totals from line items."""
    lines = details if isinstance(details, list) else []

    section_totals = {}
    tva_totals = {}
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
        "section_totals": {k: float(v.quantize(Decimal("0.01"))) for k, v in section_totals.items()},
        "tva_totals": {
            k: {"base_ht": float(v["base_ht"].quantize(Decimal("0.01"))), "tva": float(v["tva"].quantize(Decimal("0.01")))}
            for k, v in tva_totals.items()
        },
        "total_ht": float(total_ht.quantize(Decimal("0.01"))),
        "total_tva": float(total_tva.quantize(Decimal("0.01"))),
        "total_ttc": float(total_ttc.quantize(Decimal("0.01"))),
        "amount_per_person": float(amount_per_person.quantize(Decimal("0.01"))),
        "platform_fee_ht": float(platform_fee_ht.quantize(Decimal("0.01"))),
        "platform_fee_tva": float(platform_fee_tva.quantize(Decimal("0.01"))),
        "platform_fee_ttc": float(platform_fee_ttc.quantize(Decimal("0.01"))),
        "valorisable_agefiph": float(valorisable_agefiph.quantize(Decimal("0.01"))),
    }
