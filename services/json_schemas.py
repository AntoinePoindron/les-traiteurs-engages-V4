"""Pydantic schemas validating user-supplied JSON blobs.

Audit reference: VULN-25 — fields typed `JSON` in the ORM accept arbitrary
structures from form data, allowing storage bloat and downstream crashes
when other code accesses fields that were never set. Validation at the
write boundary keeps the database honest.
"""

from pydantic import BaseModel, ConfigDict


class ServiceConfig(BaseModel):
    """Validates Caterer.service_config.

    Keys mirror the `MealType` enum (same six prestation slugs the caterer
    publishes in their catalog). Each value is a boolean indicating
    whether the caterer offers that prestation. Any extra key is rejected
    so a typo cannot silently break matching, and an attacker cannot
    stuff arbitrary data in the column.
    """

    model_config = ConfigDict(extra="forbid")

    petit_dejeuner: bool = False
    pause_gourmande: bool = False
    plateaux_repas: bool = False
    cocktail_dinatoire: bool = False
    cocktail_dejeunatoire: bool = False
    aperitif: bool = False
