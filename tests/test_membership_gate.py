"""Audit finding #4: pending-membership client_users must not access
role-protected pages until an admin approves them.

Background:
    auth.py signup: when a user signs up with the SIRET of an existing
    company, a `client_user` is created with membership_status=pending
    and the session cookie is set immediately. Before the fix, nothing
    in middleware enforced membership_status, so a pending user could
    reach /client/dashboard, /client/orders, POST /client/requests/.../
    accept-quote, etc — effectively acting on behalf of the company
    without approval.
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
            s.add(User(
                email=email,
                password_hash=bcrypt.hashpw(b"pendingpw", bcrypt.gensalt()).decode(),
                first_name="P",
                last_name="P",
                role=UserRole.client_user,
                company_id=acme.id,
                membership_status=MembershipStatus.pending,
            ))
            s.commit()
        return email, "pendingpw"
    finally:
        s.close()


def test_pending_user_cannot_access_client_dashboard(client):
    email, password = _seed_pending_user()

    resp = client.post("/login", data={"email": email, "password": password})
    assert resp.status_code == 302, (
        f"login should succeed (flow sets session even for pending); got {resp.status_code}"
    )

    resp = client.get("/client/dashboard", follow_redirects=False)
    # Before the fix: 200. After the fix: redirect to login OR a 403.
    # The authenticated action must not be permitted.
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
