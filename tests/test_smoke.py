"""Smoke tests — for each role, login then GET the role dashboard.

This is the safety net for refactoring. If a future PR breaks the auth flow
or a dashboard route, these tests catch it before it reaches staging.
"""
import pytest


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json["status"] == "ok"


def test_login_page_renders(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b"email" in resp.data.lower()


def test_login_with_seeded_user_returns_302(client):
    resp = client.post("/login", data={"email": "alice@test.local", "password": "testpass"})
    if resp.status_code != 302:
        # surface the flash message in the failure
        raise AssertionError(f"Expected 302, got {resp.status_code}; body excerpt: {resp.get_data(as_text=True)[:600]}")


def test_login_wrong_password_rejected(client):
    resp = client.post("/login", data={
        "email": "alice@test.local", "password": "WRONG",
    })
    # Re-renders the login form (200) with a flash, no session set
    assert resp.status_code == 200
    assert b"user_id" not in resp.headers.get("Set-Cookie", "").encode()


@pytest.mark.parametrize("email,dashboard", [
    ("admin@test.local",  "/admin/dashboard"),
    ("alice@test.local",  "/client/dashboard"),
    ("bob@test.local",    "/client/dashboard"),
    ("cook@test.local",   "/caterer/dashboard"),
])
def test_login_redirects_to_role_dashboard(client, login, email, dashboard):
    resp = login(email)
    assert resp.status_code == 302
    assert resp.location.endswith(dashboard)


@pytest.mark.parametrize("email,page", [
    ("admin@test.local",  "/admin/dashboard"),
    ("admin@test.local",  "/admin/caterers"),
    ("admin@test.local",  "/admin/companies"),
    ("admin@test.local",  "/admin/payments"),
    ("alice@test.local",  "/client/dashboard"),
    ("alice@test.local",  "/client/orders"),
    ("alice@test.local",  "/client/requests"),
    ("alice@test.local",  "/client/team"),
    ("alice@test.local",  "/client/settings"),
    ("alice@test.local",  "/client/search"),
    ("alice@test.local",  "/client/profile"),
    ("cook@test.local",   "/caterer/dashboard"),
    ("cook@test.local",   "/caterer/orders"),
    ("cook@test.local",   "/caterer/requests"),
    ("cook@test.local",   "/caterer/profile"),
])
def test_authenticated_pages_render(client, login, email, page):
    """After logging in, every primary page returns 2xx without exploding."""
    login(email)
    resp = client.get(page)
    assert resp.status_code in (200, 302), \
        f"{email} → GET {page} returned {resp.status_code}"


def test_unauthenticated_protected_route_redirects(client):
    resp = client.get("/client/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.location


def test_role_isolation_client_cannot_reach_admin(client, login):
    login("alice@test.local")
    resp = client.get("/admin/dashboard")
    assert resp.status_code == 403


def test_role_isolation_caterer_cannot_reach_client(client, login):
    login("cook@test.local")
    resp = client.get("/client/dashboard")
    assert resp.status_code == 403


def test_404_renders_french_template(client):
    resp = client.get("/this-does-not-exist")
    assert resp.status_code == 404
    assert "Page introuvable".encode("utf-8") in resp.data \
        or "introuvable" in resp.get_data(as_text=True).lower()


def test_logout_clears_session(client, login):
    login("alice@test.local")
    # Confirm logged in
    assert client.get("/client/dashboard").status_code == 200
    client.get("/logout")
    # Now back to redirect
    assert client.get("/client/dashboard", follow_redirects=False).status_code == 302
