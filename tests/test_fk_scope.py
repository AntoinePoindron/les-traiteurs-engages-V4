"""Regression: form input that names a foreign-key UUID outside the user's
scope must be ignored, not 500.

These cases would crash the app prior to PR 14 because the handler accepted
any well-formed UUID and let Postgres reject the INSERT with FK violation.
"""


def _own_company_service_id(client, login):
    """Create a CompanyService for alice and return its id (str)."""
    from database import get_db
    from models import CompanyService
    from sqlalchemy import select

    login("alice@test.local")
    with client.application.app_context():
        db = get_db()
        s = db.scalar(select(CompanyService).limit(1))
        if s:
            return str(s.id)
        # No service yet — let alice create one through the UI
    resp = client.post("/client/team/services", data={"name": "Test Service"})
    assert resp.status_code in (200, 302)
    with client.application.app_context():
        db = get_db()
        s = db.scalar(select(CompanyService).limit(1))
        return str(s.id)


def test_quote_request_with_bogus_company_service_id_does_not_500(client, login):
    login("alice@test.local")
    resp = client.post("/client/requests/new", data={
        "company_service_id": "00000000-0000-0000-0000-000000000000",
        "service_type": "test",
        "meal_type": "dejeuner",
        "event_date": "2026-12-25",
        "guest_count": 20,
    })
    assert resp.status_code != 500, "FK to nonexistent service should not 500"
    assert resp.status_code in (200, 302, 400)


def test_employee_with_bogus_service_id_does_not_500(client, login):
    login("alice@test.local")
    resp = client.post("/client/team/employees", data={
        "first_name": "Test",
        "last_name": "User",
        "email": "test@example.com",
        "service_id": "00000000-0000-0000-0000-000000000000",
    })
    assert resp.status_code != 500, "FK to nonexistent service should not 500"


def test_quote_request_cannot_attach_to_other_company_service(client, login):
    """Even if alice knows bob's service_id, the form must drop it."""
    from database import get_db
    from models import Company, CompanyService
    from sqlalchemy import select

    with client.application.app_context():
        db = get_db()
        bob_company = db.scalar(select(Company).where(Company.name != "ACME Test").limit(1))
        if bob_company is None:
            # set up a second company
            other = Company(name="Other Co", siret="00000000000001")
            db.add(other)
            db.flush()
            other_service = CompanyService(company_id=other.id, name="Their service")
            db.add(other_service)
            db.commit()
            other_id = str(other_service.id)
        else:
            other_service = db.scalar(select(CompanyService).where(
                CompanyService.company_id == bob_company.id
            ))
            if other_service is None:
                other_service = CompanyService(company_id=bob_company.id, name="Their service")
                db.add(other_service)
                db.commit()
            other_id = str(other_service.id)

    login("alice@test.local")
    resp = client.post("/client/requests/new", data={
        "company_service_id": other_id,
        "service_type": "test",
        "meal_type": "dejeuner",
        "event_date": "2026-12-25",
        "guest_count": 20,
    })
    assert resp.status_code in (200, 302), f"unexpected status {resp.status_code}"

    # The created QuoteRequest must NOT carry bob's service_id.
    from models import QuoteRequest
    with client.application.app_context():
        db = get_db()
        rows = db.scalars(select(QuoteRequest).order_by(QuoteRequest.created_at.desc()).limit(1)).all()
        assert rows, "expected the QuoteRequest to be created"
        assert str(rows[0].company_service_id) != other_id, \
            "alice should not be able to link her quote_request to another company's service"
