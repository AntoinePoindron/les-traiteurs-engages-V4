"""Red/green tests for the CGS-acceptance gate on signup.

Four server-side paths create a User and each must (a) refuse the
signup when `accept_terms` is absent, and (b) stamp the active
`TermsVersion` id + the wall-clock `terms_accepted_at` on the new
row. These tests freeze that contract so a refactor of the signup
flow can't silently lose the legal trace.

Coverage:
  * POST /signup as client_admin on a fresh SIRET
  * POST /signup as client_admin against an existing SIRET (pending)
  * POST /signup as caterer
  * POST /signup/invite/<token>
  * services.terms.current_terms_version date-tie selection
"""


def _wipe_signup_users():
    """Remove users this suite seeds so cross-test state stays clean.

    Signup auto-creates a CompanyEmployee row tied to every new
    client_admin / client_user via `_ensure_admin_employee_rows`, so we
    must drop those FK-referencing rows before the users themselves —
    otherwise the delete trips `company_employees_user_id_fkey`.
    """
    from sqlalchemy import select

    from database import session_factory
    from models import CompanyEmployee, User

    s = session_factory()
    try:
        user_ids = list(
            s.scalars(select(User.id).where(User.email.like("terms-%@test.local")))
        )
        if user_ids:
            s.execute(
                CompanyEmployee.__table__.delete().where(
                    CompanyEmployee.user_id.in_(user_ids)
                )
            )
        s.execute(User.__table__.delete().where(User.email.like("terms-%@test.local")))
        s.commit()
    finally:
        s.close()


def _wipe_signup_companies(siret_prefix: str = "9999"):
    """Drop any Company seeded with a `terms-*` SIRET prefix.

    Signup auto-seeds a CompanyService and CompanyEmployee row for a
    freshly-created Company, so we drop those FK-referencing rows
    first — otherwise the delete trips company_services_company_id_fkey
    / company_employees_company_id_fkey.
    """
    from sqlalchemy import select

    from database import session_factory
    from models import Company, CompanyEmployee, CompanyService

    s = session_factory()
    try:
        company_ids = list(
            s.scalars(select(Company.id).where(Company.siret.startswith(siret_prefix)))
        )
        if company_ids:
            s.execute(
                CompanyService.__table__.delete().where(
                    CompanyService.company_id.in_(company_ids)
                )
            )
            s.execute(
                CompanyEmployee.__table__.delete().where(
                    CompanyEmployee.company_id.in_(company_ids)
                )
            )
        s.execute(
            Company.__table__.delete().where(Company.siret.startswith(siret_prefix))
        )
        s.commit()
    finally:
        s.close()


def _seed_extra_terms_version(slug: str, effective_at):
    """Insert one extra TermsVersion so the date-resolver has multiple
    rows to choose from. Returns its id."""
    from database import session_factory
    from models import TermsVersion

    s = session_factory()
    try:
        row = TermsVersion(
            slug=slug,
            title=f"CGS {slug}",
            template_name=f"legal/cgs_{slug}.html",
            effective_at=effective_at,
        )
        s.add(row)
        s.commit()
        return row.id
    finally:
        s.close()


def _drop_terms_version(row_id):
    from database import session_factory
    from models import TermsVersion

    s = session_factory()
    try:
        s.execute(TermsVersion.__table__.delete().where(TermsVersion.id == row_id))
        s.commit()
    finally:
        s.close()


def _fetch_user(email):
    from sqlalchemy import select

    from database import session_factory
    from models import User

    s = session_factory()
    try:
        return s.scalar(select(User).where(User.email == email))
    finally:
        s.close()


def _active_terms_id():
    """Return the id of whichever TermsVersion is currently in force,
    as the route would resolve it at submit time."""
    from database import session_factory
    from services.terms import current_terms_version

    s = session_factory()
    try:
        return current_terms_version(s).id
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Gate: no accept_terms → no User
# ---------------------------------------------------------------------------


def test_signup_client_admin_refuses_without_accept_terms(client):
    """Without `accept_terms`, the new-SIRET client_admin path must
    re-render the form (200) and create no User. The legal gate is the
    headline contract of this PR — it can't be bypassed by omitting the
    field."""
    try:
        r = client.post(
            "/signup",
            data={
                "role": "client_admin",
                "email": "terms-newadmin@test.local",
                "password": "VeryStrongPw1!",
                "first_name": "Term",
                "last_name": "Refuse",
                "siret": "99990000000001",
            },
            follow_redirects=False,
        )
        assert r.status_code == 200, (
            f"signup without accept_terms must re-render, not redirect; got "
            f"{r.status_code}"
        )
        assert _fetch_user("terms-newadmin@test.local") is None, (
            "no User row may be created when accept_terms is missing"
        )
    finally:
        _wipe_signup_users()
        _wipe_signup_companies()


def test_signup_caterer_refuses_without_accept_terms(client):
    """Same gate must hold for the caterer signup path — it's a
    different branch of the same handler, easy to miss in a refactor."""
    try:
        r = client.post(
            "/signup",
            data={
                "role": "caterer",
                "email": "terms-cook@test.local",
                "password": "VeryStrongPw1!",
                "first_name": "Term",
                "last_name": "Cook",
                "siret": "99990000000002",
            },
            follow_redirects=False,
        )
        assert r.status_code == 200, r.data
        assert _fetch_user("terms-cook@test.local") is None
    finally:
        _wipe_signup_users()
        _wipe_signup_companies()


def test_signup_invite_refuses_without_accept_terms(client):
    """The invite-redemption path creates a third User-instantiation
    site — must enforce the same gate."""
    import datetime as _dt

    from sqlalchemy import select

    from database import session_factory
    from models import CompanyEmployee

    # Seed an invite row on the ACME company so the redemption is valid
    # apart from the missing accept_terms.
    token = "terms-refusal-token-eeeeeeeeeeeeeeeeeeeeeeeeeeee"
    s = session_factory()
    try:
        from models import Company

        acme = s.scalar(select(Company).where(Company.siret == "12345678901234"))
        emp = CompanyEmployee(
            company_id=acme.id,
            email="terms-invitee@test.local",
            first_name="Term",
            last_name="Invite",
            invite_token=token,
            invited_at=_dt.datetime.utcnow(),
        )
        s.add(emp)
        s.commit()
        emp_id = emp.id
    finally:
        s.close()

    try:
        r = client.post(
            f"/signup/invite/{token}",
            data={"password": "VeryStrongPw1!"},  # no accept_terms
            follow_redirects=False,
        )
        assert r.status_code == 200, (
            f"invite redemption without accept_terms must re-render; got "
            f"{r.status_code}"
        )
        assert _fetch_user("terms-invitee@test.local") is None
    finally:
        _wipe_signup_users()
        s = session_factory()
        try:
            s.execute(
                CompanyEmployee.__table__.delete().where(CompanyEmployee.id == emp_id)
            )
            s.commit()
        finally:
            s.close()


# ---------------------------------------------------------------------------
# Stamp: accepted → version + timestamp on the User
# ---------------------------------------------------------------------------


def test_signup_client_admin_stamps_terms_version_and_timestamp(client):
    """Successful signup must persist the active TermsVersion id and a
    non-null acceptance timestamp — that's the legal trace."""
    active_id = _active_terms_id()
    try:
        r = client.post(
            "/signup",
            data={
                "role": "client_admin",
                "email": "terms-stamped@test.local",
                "password": "VeryStrongPw1!",
                "first_name": "Term",
                "last_name": "Stamped",
                "siret": "99990000000003",
                "accept_terms": "on",
            },
            follow_redirects=False,
        )
        assert r.status_code == 302, r.data

        u = _fetch_user("terms-stamped@test.local")
        assert u is not None, "successful signup must create the User"
        assert u.terms_accepted_version_id == active_id, (
            "stamp must match whichever version was in force at submit time"
        )
        assert u.terms_accepted_at is not None, (
            "terms_accepted_at must carry the wall-clock acceptance moment"
        )
    finally:
        _wipe_signup_users()
        _wipe_signup_companies()


def test_signup_pending_client_user_stamps_terms_too(client):
    """Joining an existing SIRET creates a `client_user` in pending
    state. That row is still a real User and must carry the same legal
    trace as a standalone signup — otherwise the approval-pending path
    drops the audit silently."""
    active_id = _active_terms_id()
    try:
        r = client.post(
            "/signup",
            data={
                "role": "client_admin",
                "email": "terms-pending@test.local",
                "password": "VeryStrongPw1!",
                "first_name": "Term",
                "last_name": "Pending",
                "siret": "12345678901234",  # ACME, pre-seeded
                "accept_terms": "1",
            },
            follow_redirects=False,
        )
        assert r.status_code == 302, r.data

        u = _fetch_user("terms-pending@test.local")
        assert u is not None
        assert u.terms_accepted_version_id == active_id
        assert u.terms_accepted_at is not None
    finally:
        _wipe_signup_users()


# ---------------------------------------------------------------------------
# Resolver: which version is in force on a given date?
# ---------------------------------------------------------------------------


def test_current_terms_version_picks_the_latest_effective_row(app):
    """When two versions exist, the helper must return the one with the
    highest `effective_at <= today`. Future versions stay invisible
    until their effective date arrives."""
    import datetime as _dt

    from database import session_factory
    from services.terms import current_terms_version

    # Seed a v-future and a v-past so we have three rows total
    # alongside the migration-seeded v1.
    past_id = _seed_extra_terms_version("vpast", _dt.date(2020, 1, 1))
    future_id = _seed_extra_terms_version(
        "vfuture", _dt.date.today() + _dt.timedelta(days=365)
    )
    try:
        s = session_factory()
        try:
            # Today: the helper must NOT pick the future row.
            today_active = current_terms_version(s, today=_dt.date.today())
            assert today_active.id != future_id, (
                "future version must not be 'in force' on today"
            )

            # Far past: the v-past row is the only one effective.
            past_active = current_terms_version(s, today=_dt.date(2020, 6, 1))
            assert past_active.id == past_id, (
                "the date-tie resolver must pick the past row when today < v1"
            )

            # Far future: the v-future row wins.
            far_future = current_terms_version(
                s, today=_dt.date.today() + _dt.timedelta(days=400)
            )
            assert far_future.id == future_id, (
                "once a future version's effective_at is reached it must win"
            )
        finally:
            s.close()
    finally:
        _drop_terms_version(past_id)
        _drop_terms_version(future_id)
