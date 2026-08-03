"""Tests for interim self-signup (2026-07-20, flag: IA_SELF_SIGNUP).

Covers:
- signup happy path incl. immediate login (no separate /login call needed —
  the signup response itself is a valid session);
- duplicate email -> 409;
- weak password -> 422 (pydantic validation);
- flag off -> 404 (endpoint hidden);
- seeded (baked-in allow-list) admins still log in after the DB migration;
- migration idempotency (init_users_table can run twice safely);
- basic in-process signup rate limit.
"""

import json
from pathlib import Path
from unittest.mock import patch

import bcrypt
import pytest
from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def allowed_users_file(tmp_path):
    """Write a temporary allow-list with one bcrypt admin user and patch USERS_FILE."""
    pw = "correct-horse"
    h = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    path = tmp_path / "allowed_users.json"
    path.write_text(json.dumps({"users": [
        {"email": "seeded.admin@cgiar.org", "name": "Seeded Admin", "role": "admin", "password_hash": h},
    ]}))
    with patch("synapsis.config.USERS_FILE", path), patch("synapsis.auth.users.USERS_FILE", path):
        yield {"email": "seeded.admin@cgiar.org", "password": pw}


@pytest.fixture
async def signup_client(initialized_db: Path, allowed_users_file):
    """Async client with self-signup ENABLED and the DB re-seeded from the
    (patched) allow-list JSON, matching what a real boot does."""
    from synapsis.database.users import init_users_table

    with (
        patch("synapsis.database.DB_PATH", initialized_db),
        patch("synapsis.auth.routes.SELF_SIGNUP_ENABLED", True),
        patch("synapsis.routes.health.SELF_SIGNUP_ENABLED", True),
        patch("synapsis.config.AUTH_DISABLED", False),
        patch("synapsis.auth.middleware.AUTH_DISABLED", False),
    ):
        # Re-run the seed now that USERS_FILE points at our temp allow-list
        # (initialized_db already ran init_db() once, before the patch above
        # took effect, so it seeded nothing).
        await init_users_table()

        # Reset the in-process rate limiter between tests so they don't
        # interfere with each other (module-level dict persists across tests
        # in the same process).
        import synapsis.auth.routes as routes_mod
        routes_mod._signup_attempts.clear()

        from synapsis.server import app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


@pytest.fixture
async def signup_client_flag_off(initialized_db: Path, allowed_users_file):
    """Same as signup_client but with the flag OFF (default)."""
    from synapsis.database.users import init_users_table

    with (
        patch("synapsis.database.DB_PATH", initialized_db),
        patch("synapsis.auth.routes.SELF_SIGNUP_ENABLED", False),
        patch("synapsis.routes.health.SELF_SIGNUP_ENABLED", False),
        patch("synapsis.config.AUTH_DISABLED", False),
        patch("synapsis.auth.middleware.AUTH_DISABLED", False),
    ):
        await init_users_table()
        import synapsis.auth.routes as routes_mod
        routes_mod._signup_attempts.clear()

        from synapsis.server import app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


# ---------------------------------------------------------------------------
# Happy path + immediate login
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_signup_happy_path_grants_immediate_access(signup_client):
    resp = await signup_client.post(
        "/api/auth/signup",
        json={"name": "New Researcher", "email": "new.researcher@cgiar.org", "password": "s3cure-pw"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert "token" in data and data["token"]
    assert data["user"]["email"] == "new.researcher@cgiar.org"
    assert data["user"]["role"] == "researcher"

    # The returned token works immediately -- no separate confirmation step.
    me = await signup_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {data['token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "new.researcher@cgiar.org"

    # And a fresh /login with the chosen password also succeeds.
    login = await signup_client.post(
        "/api/auth/login",
        json={"email": "new.researcher@cgiar.org", "password": "s3cure-pw"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "researcher"


@pytest.mark.asyncio
async def test_signup_email_is_lowercased_and_trimmed(signup_client):
    resp = await signup_client.post(
        "/api/auth/signup",
        json={"name": "Case Test", "email": "  Mixed.Case@CGIAR.org  ", "password": "s3cure-pw"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["user"]["email"] == "mixed.case@cgiar.org"


# ---------------------------------------------------------------------------
# Duplicate email -> 409
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_signup_duplicate_email_rejected(signup_client):
    body = {"name": "Dup", "email": "dup@cgiar.org", "password": "s3cure-pw"}
    first = await signup_client.post("/api/auth/signup", json=body)
    assert first.status_code == 201

    second = await signup_client.post("/api/auth/signup", json=body)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_signup_duplicate_of_seeded_admin_rejected(signup_client, allowed_users_file):
    # seeded.admin@cgiar.org already exists via the allow-list seed migration.
    resp = await signup_client.post(
        "/api/auth/signup",
        json={"name": "Impersonator", "email": allowed_users_file["email"], "password": "s3cure-pw"},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Weak password -> 422
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_signup_weak_password_rejected(signup_client):
    resp = await signup_client.post(
        "/api/auth/signup",
        json={"name": "Weak", "email": "weak@cgiar.org", "password": "short"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_signup_invalid_email_rejected(signup_client):
    resp = await signup_client.post(
        "/api/auth/signup",
        json={"name": "Bad Email", "email": "not-an-email", "password": "s3cure-pw"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Flag off -> 404
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_signup_returns_404_when_flag_off(signup_client_flag_off):
    resp = await signup_client_flag_off.post(
        "/api/auth/signup",
        json={"name": "Nope", "email": "nope@cgiar.org", "password": "s3cure-pw"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_config_reports_self_signup_true_when_flag_on(signup_client):
    # NOTE: SELF_SIGNUP_ENABLED is a process-global module attribute, so this
    # and the "off" case below are deliberately separate tests (not combined
    # with both client fixtures active at once, which would race on the same
    # global and make the assertion order-dependent).
    on = await signup_client.get("/api/config")
    assert on.json()["self_signup"] is True


@pytest.mark.asyncio
async def test_config_reports_self_signup_false_when_flag_off(signup_client_flag_off):
    off = await signup_client_flag_off.get("/api/config")
    assert off.json()["self_signup"] is False


# ---------------------------------------------------------------------------
# Seeded admins still log in after the DB migration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_seeded_admin_still_logs_in_after_migration(signup_client, allowed_users_file):
    resp = await signup_client.post(
        "/api/auth/login",
        json={"email": allowed_users_file["email"], "password": allowed_users_file["password"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["role"] == "admin"


# ---------------------------------------------------------------------------
# Migration idempotency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_migration_is_idempotent_and_never_overwrites_existing_hash(
    initialized_db: Path, allowed_users_file
):
    from synapsis.database.users import init_users_table, get_user_row
    from synapsis.auth.users import hash_password

    with patch("synapsis.database.DB_PATH", initialized_db):
        # Re-seed from the (patched) allow-list.
        await init_users_table()
        row1 = await get_user_row(allowed_users_file["email"])
        assert row1 is not None

        # Simulate a user who signed up with the SAME email as a baked-in
        # allow-list entry, choosing their own password.
        new_hash = hash_password("their-own-password")
        from synapsis.database import _get_shared_db
        db = await _get_shared_db()
        await db.execute(
            "UPDATE users SET password_hash = ? WHERE email = ?",
            (new_hash, allowed_users_file["email"]),
        )
        await db.commit()

        # Re-running the migration (as every boot does) must NOT overwrite
        # the user's own hash back to the baked-in one.
        await init_users_table()
        await init_users_table()  # twice, for good measure -- no error, no drift

        row2 = await get_user_row(allowed_users_file["email"])
        assert row2["password_hash"] == new_hash
        assert row2["password_hash"] != row1["password_hash"]


# ---------------------------------------------------------------------------
# Rate limit (minimal abuse guard)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_signup_rate_limit_kicks_in_after_five_per_minute(signup_client):
    for i in range(5):
        resp = await signup_client.post(
            "/api/auth/signup",
            json={"name": f"User {i}", "email": f"rl{i}@cgiar.org", "password": "s3cure-pw"},
        )
        assert resp.status_code == 201, resp.text

    sixth = await signup_client.post(
        "/api/auth/signup",
        json={"name": "Sixth", "email": "rl5@cgiar.org", "password": "s3cure-pw"},
    )
    assert sixth.status_code == 429


# ---------------------------------------------------------------------------
# Domain allow-list (IA_SIGNUP_ALLOWED_DOMAINS, default "cgiar.org")
#
# Jose -> Marc Schut, 2026-07-22: signup "is not allowed to avoid anyone just
# using it (without a CG email)". These tests pin the code to that policy.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_signup_allowed_domain_passes(signup_client):
    """Default allow-list (cgiar.org) lets a CGIAR address through."""
    resp = await signup_client.post(
        "/api/auth/signup",
        json={"name": "Allowed", "email": "allowed.person@cgiar.org", "password": "s3cure-pw"},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_signup_disallowed_domain_rejected_with_403_and_message(signup_client):
    resp = await signup_client.post(
        "/api/auth/signup",
        json={"name": "Outsider", "email": "outsider@gmail.com", "password": "s3cure-pw"},
    )
    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert "@cgiar.org" in detail
    assert "restricted" in detail.lower()


@pytest.mark.asyncio
async def test_signup_domain_check_is_case_insensitive(signup_client):
    """Upper-case domains are accepted (and the stored email lower-cased)."""
    resp = await signup_client.post(
        "/api/auth/signup",
        json={"name": "Shouty", "email": "Shouty.Person@CGIAR.ORG", "password": "s3cure-pw"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["user"]["email"] == "shouty.person@cgiar.org"


@pytest.mark.asyncio
async def test_signup_subdomain_does_not_match(signup_client):
    """Exact-domain semantics: mail.cgiar.org is NOT cgiar.org."""
    resp = await signup_client.post(
        "/api/auth/signup",
        json={"name": "Sub", "email": "sub@mail.cgiar.org", "password": "s3cure-pw"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_signup_domain_allow_list_is_config_overridable(signup_client):
    """Extra domains can be added without a code change."""
    with patch(
        "synapsis.auth.routes.SIGNUP_ALLOWED_DOMAINS", ["cgiar.org", "cimmyt.org"]
    ):
        ok = await signup_client.post(
            "/api/auth/signup",
            json={"name": "Centre", "email": "centre.person@cimmyt.org", "password": "s3cure-pw"},
        )
        assert ok.status_code == 201, ok.text

        nope = await signup_client.post(
            "/api/auth/signup",
            json={"name": "Other", "email": "other@example.org", "password": "s3cure-pw"},
        )
        assert nope.status_code == 403, nope.text
        assert "@cimmyt.org" in nope.json()["detail"]


@pytest.mark.asyncio
async def test_signup_empty_allow_list_disables_the_restriction(signup_client):
    """IA_SIGNUP_ALLOWED_DOMAINS="*" parses to [] = no restriction."""
    with patch("synapsis.auth.routes.SIGNUP_ALLOWED_DOMAINS", []):
        resp = await signup_client.post(
            "/api/auth/signup",
            json={"name": "Anyone", "email": "anyone@example.com", "password": "s3cure-pw"},
        )
        assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_signup_flag_off_still_404_even_for_allowed_domain(signup_client_flag_off):
    """The flag gate keeps precedence over the domain check (endpoint hidden)."""
    resp = await signup_client_flag_off.post(
        "/api/auth/signup",
        json={"name": "Nope", "email": "nope@cgiar.org", "password": "s3cure-pw"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_config_reports_signup_allowed_domains(signup_client):
    cfg = await signup_client.get("/api/config")
    assert cfg.json()["signup_allowed_domains"] == ["cgiar.org"]


# ---------------------------------------------------------------------------
# Allow-list parsing (pure function — no HTTP)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ["cgiar.org"]),            # unset -> restrictive default
        ("", ["cgiar.org"]),              # blank -> restrictive default (fail closed)
        ("   ", ["cgiar.org"]),           # whitespace -> restrictive default
        (",,", ["cgiar.org"]),            # only separators -> restrictive default
        ("*", []),                        # explicit opt-out -> no restriction
        ("cgiar.org,*", []),              # "*" anywhere wins
        ("CGIAR.org", ["cgiar.org"]),     # lower-cased
        ("@cgiar.org", ["cgiar.org"]),    # leading @ tolerated
        (" cgiar.org , cimmyt.org ", ["cgiar.org", "cimmyt.org"]),
    ],
)
def test_parse_signup_allowed_domains(raw, expected):
    from synapsis.config import _parse_signup_allowed_domains

    assert _parse_signup_allowed_domains(raw) == expected
