import random
import string

from sqlalchemy import select

from models import Caterer


def generate_invoice_prefix(session):
    """Generate a unique invoice prefix for a caterer."""
    for length in (5, 8, 10):
        slug = "".join(random.choices(string.ascii_uppercase, k=length))
        existing = session.execute(
            select(Caterer.id).where(Caterer.invoice_prefix == slug)
        ).first()
        if not existing:
            return slug
    while True:
        slug = str(random.randint(10000, 9999999999))
        existing = session.execute(
            select(Caterer.id).where(Caterer.invoice_prefix == slug)
        ).first()
        if not existing:
            return slug
