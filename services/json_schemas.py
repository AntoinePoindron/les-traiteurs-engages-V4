"""Pydantic schemas validating user-supplied JSON blobs.

Audit reference: VULN-25 — fields typed `JSON` in the ORM accept arbitrary
structures from form data, allowing storage bloat and downstream crashes
when other code accesses fields that were never set. Validation at the
write boundary keeps the database honest.
"""
from pydantic import BaseModel, ConfigDict


class ServiceConfig(BaseModel):
    """Validates Caterer.service_config.

    Keys are the MealType enum values; each value is a boolean indicating
    whether the caterer offers that meal type. Any extra key is rejected
    so a typo (`dejeunner` instead of `dejeuner`) cannot silently break
    matching, and an attacker cannot stuff arbitrary data in the column.
    """
    model_config = ConfigDict(extra="forbid")

    dejeuner: bool = False
    diner: bool = False
    cocktail: bool = False
    petit_dejeuner: bool = False
    autre: bool = False
