"""Audit finding #4: pending-membership client_users must not access
role-protected pages until an admin approves them.

Background:
    auth.py signup: when a user signs up with the SIRET of an existing
    company, a `client_user` is created with membership_status=pending.
    No session is issued at signup time, and /login refuses pending
    users upfront. Defense in depth: app.py.load_current_user wipes
    g.current_user for any session pointing at a pending/rejected user
    so a stale cookie can't bypass the login check.

    Without this gate, a pending user could read /client/dashboard,
    /client/orders, /client/messages, etc — leaking the company's
    quote requests, orders, internal DMs and budget figures to anyone
    who can sign up with the company's (public) SIRET.
"""


def _seed_pending_user():
    """Create a `client_user` with membership_status=pending attached to
    the existing ACME Test company, matching the signup-to-existing-SIRET
    flow. Returns (email, password)."""
    import bcrypt
    from sqlalchemy import select

    from database import session_factory
    from models import Company, MembershipStatus, User, UserRole

    s = session_factory()
    try:
        acme = s.scalar(select(Company).where(Company.siret == "12345678901234"))
        email = "pending@test.local"
        existing = s.scalar(select(User).where(User.email == email))
        if existing is None:
            s.add(
                User(
                    email=email,
                    password_hash=bcrypt.hashpw(
                        b"pendingpw", bcrypt.gensalt()
                    ).decode(),
                    first_name="P",
                    last_name="P",
                    role=UserRole.client_user,
                    company_id=acme.id,
                    membership_status=MembershipStatus.pending,
                )
            )
            s.commit()
        return email, "pendingpw"
    finally:
        s.close()


def test_pending_user_login_refused(client):
    """/login must not issue a session for pending users — a 200 with
    the login page (not a 302 to the dashboard) is the success criterion."""
    email, password = _seed_pending_user()

    resp = client.post(
        "/login", data={"email": email, "password": password}, follow_redirects=False
    )
    assert resp.status_code == 200, (
        f"login must NOT redirect a pending user to a dashboard; got {resp.status_code}"
    )


def test_pending_user_cannot_access_client_dashboard(client):
    """Even if a stale session cookie smuggles in a pending user's id,
    load_current_user wipes g.current_user and protected routes redirect."""
    email, password = _seed_pending_user()

    # The login attempt above should not have persisted a session, but we
    # follow it through to be sure protected pages still bounce.
    client.post("/login", data={"email": email, "password": password})

    resp = client.get("/client/dashboard", follow_redirects=False)
    assert resp.status_code in (302, 403), (
        f"pending member must be blocked; got {resp.status_code}"
    )


def test_pending_user_cannot_access_client_orders(client):
    email, password = _seed_pending_user()
    client.post("/login", data={"email": email, "password": password})

    resp = client.get("/client/orders", follow_redirects=False)
    assert resp.status_code in (302, 403), (
        f"pending member must be blocked from orders; got {resp.status_code}"
    )


def test_active_user_still_accesses_dashboard(client, login):
    """Regression guard: non-pending users stay functional after the gate."""
    login("alice@test.local")
    resp = client.get("/client/dashboard", follow_redirects=False)
    assert resp.status_code == 200, (
        f"active client_admin should still reach dashboard; got {resp.status_code}"
    )
