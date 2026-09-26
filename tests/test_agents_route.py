"""
Tests for synapsis/routes/agents.py

Uses httpx.AsyncClient with FastAPI's ASGITransport to hit the real route
handlers without starting a network server. The ``test_client`` fixture
(defined in conftest.py) provides a properly DB-patched async client so
each test operates on an isolated temp database.
"""

import json
import time
import pytest
import aiosqlite
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _insert_custom_agent(db_path: Path, agent_id: str = "my_custom_agent", name: str = "My Custom") -> None:
    """Directly insert a custom agent row for test setup."""
    now = time.time()
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(
            """INSERT INTO agents (id, name, description, system_prompt, tools, model,
               color, type, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'custom', 1, ?, ?)""",
            (agent_id, name, "A custom agent", "You are helpful.", "[]", "sonnet", "#ff0000", now, now),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# List agents
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_agents_includes_builtins(test_client, initialized_db: Path):
    """GET /api/agents includes the IA builtin agents and the orchestrator.

    The Synapsis GUI/shell specialists (computer_use, code_automation) are no
    longer part of the IA roster (sandbox 2026-09-26).
    """
    resp = await test_client.get("/api/agents")

    assert resp.status_code == 200
    data = resp.json()
    agent_ids = {a["id"] for a in data["agents"]}
    expected = {"data_analysis", "visualization_reporting", "research_methodology",
                "prms_data_analyst", "orchestrator"}
    assert expected.issubset(agent_ids), f"Missing agents: {expected - agent_ids}"
    assert not agent_ids & {"computer_use", "code_automation"}


@pytest.mark.asyncio
async def test_list_agents_includes_custom(test_client, initialized_db: Path):
    """GET /api/agents includes custom agents stored in the database."""
    await _insert_custom_agent(initialized_db, agent_id="test_custom_001", name="Test Custom Agent")

    resp = await test_client.get("/api/agents")

    agent_ids = {a["id"] for a in resp.json()["agents"]}
    assert "test_custom_001" in agent_ids


# ---------------------------------------------------------------------------
# Get single agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_builtin_agent(test_client):
    """GET /api/agents/data_analysis returns the correct builtin agent details."""
    resp = await test_client.get("/api/agents/data_analysis")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "data_analysis"
    assert data["type"] == "builtin"
    assert data["status"] == "active"
    assert isinstance(data["tools"], list)


@pytest.mark.asyncio
async def test_get_orchestrator(test_client):
    """GET /api/agents/orchestrator returns the special orchestrator entry."""
    resp = await test_client.get("/api/agents/orchestrator")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "orchestrator"
    assert data["type"] == "builtin"


@pytest.mark.asyncio
async def test_get_nonexistent_agent_404(test_client):
    """GET /api/agents/<unknown_id> returns HTTP 404."""
    resp = await test_client.get("/api/agents/definitely_does_not_exist_xyz")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Create agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_agent_valid(test_client):
    """POST /api/agents with a valid payload creates an agent and returns it."""
    payload = {
        "name": "My New Agent",
        "description": "An agent for testing",
        "system_prompt": "You are a helpful test agent.",
        "tools": ["Read", "Bash"],
        "model": "sonnet",
        "color": "#aabbcc",
    }
    resp = await test_client.post("/api/agents", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "My New Agent"
    assert data["type"] == "custom"
    assert data["model"] == "sonnet"
    assert set(data["tools"]) == {"Read", "Bash"}


@pytest.mark.asyncio
async def test_create_agent_validates_tools(test_client):
    """POST /api/agents with an invalid tool name returns HTTP 400."""
    payload = {
        "name": "Bad Tools Agent",
        "description": "Testing tool validation",
        "system_prompt": "You are helpful.",
        "tools": ["Read", "FakeTool"],
        "model": "sonnet",
    }
    resp = await test_client.post("/api/agents", json=payload)

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_agent_validates_model(test_client):
    """POST /api/agents with an invalid model returns HTTP 400."""
    payload = {
        "name": "Bad Model Agent",
        "description": "Testing model validation",
        "system_prompt": "You are helpful.",
        "tools": [],
        "model": "gpt-4-turbo",  # not allowed
    }
    resp = await test_client.post("/api/agents", json=payload)

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_agent_validates_name_length(test_client):
    """POST /api/agents with an empty name returns HTTP 400."""
    payload = {
        "name": "",  # empty name is invalid
        "description": "Testing name validation",
        "system_prompt": "You are helpful.",
        "tools": [],
        "model": "sonnet",
    }
    resp = await test_client.post("/api/agents", json=payload)

    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Update agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_agent(test_client, initialized_db: Path):
    """PUT /api/agents/{id} updates only the provided fields."""
    await _insert_custom_agent(initialized_db, agent_id="update_me", name="Original Name")

    resp = await test_client.put(
        "/api/agents/update_me",
        json={"name": "Updated Name", "model": "opus"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated Name"
    assert data["model"] == "opus"


@pytest.mark.asyncio
async def test_update_builtin_blocked(test_client):
    """PUT /api/agents/<builtin_id> must return HTTP 403."""
    resp = await test_client.put(
        "/api/agents/data_analysis",
        json={"name": "Hacked Name"},
    )

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Delete agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_agent_soft_delete(test_client, initialized_db: Path):
    """DELETE /api/agents/{id} sets is_active=0, not a hard delete."""
    await _insert_custom_agent(initialized_db, agent_id="to_delete", name="Deleteable")

    resp = await test_client.delete("/api/agents/to_delete")

    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"

    # Row still exists but is inactive
    async with aiosqlite.connect(str(initialized_db)) as db:
        cursor = await db.execute(
            "SELECT is_active FROM agents WHERE id = 'to_delete'"
        )
        row = await cursor.fetchone()

    assert row is not None, "Row was physically deleted"
    assert row[0] == 0, "Expected is_active=0 after soft-delete"


@pytest.mark.asyncio
async def test_delete_builtin_blocked(test_client):
    """DELETE /api/agents/<builtin_id> must return HTTP 403."""
    resp = await test_client.delete("/api/agents/data_analysis")

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Clone agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clone_builtin_agent(test_client):
    """POST /api/agents/<builtin_id>/clone creates a new custom agent."""
    resp = await test_client.post("/api/agents/data_analysis/clone")

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "custom"
    assert "Copy" in data["name"]
    assert data["parent_agent"] == "data_analysis"


@pytest.mark.asyncio
async def test_clone_custom_agent(test_client, initialized_db: Path):
    """POST /api/agents/<custom_id>/clone creates a copy of a custom agent."""
    await _insert_custom_agent(initialized_db, agent_id="original_custom", name="Original Custom")

    resp = await test_client.post("/api/agents/original_custom/clone")

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "custom"
    assert "Copy" in data["name"]
    assert data["parent_agent"] == "original_custom"


# ---------------------------------------------------------------------------
# Test agent config validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_test_agent_valid_config(test_client):
    """POST /api/agents/<builtin_id>/test returns valid=True for a well-configured builtin."""
    resp = await test_client.post("/api/agents/data_analysis/test", json={})

    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["issues"] == []


@pytest.mark.asyncio
async def test_test_agent_invalid_config(test_client, initialized_db: Path):
    """POST /api/agents/{id}/test returns valid=False for an agent with empty system_prompt."""
    # Insert a custom agent with an empty system_prompt to trigger a validation issue
    now = time.time()
    async with aiosqlite.connect(str(initialized_db)) as db:
        await db.execute(
            """INSERT INTO agents (id, name, description, system_prompt, tools, model,
               color, type, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'custom', 1, ?, ?)""",
            ("bad_config_agent", "Bad Config", "desc", "   ", "[]", "sonnet", "#000", now, now),
        )
        await db.commit()

    resp = await test_client.post("/api/agents/bad_config_agent/test", json={})

    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    assert len(data["issues"]) > 0


# ---------------------------------------------------------------------------
# Access control (2026-09-26, review L1-06 / L7-03): writes are admin-only;
# reading the roster and the persona picker stays open to every signed-in user.
# ---------------------------------------------------------------------------

def _bearer(user_id: str, role: str) -> dict:
    from synapsis.auth.tokens import create_access_token
    return {"Authorization": f"Bearer {create_access_token(user_id, user_id.split('@')[0], role)}"}


@pytest.fixture
async def enforced_client(initialized_db: Path):
    from httpx import AsyncClient, ASGITransport
    with (
        patch("synapsis.config.AUTH_DISABLED", False),
        patch("synapsis.auth.middleware.AUTH_DISABLED", False),
        patch("synapsis.database.DB_PATH", initialized_db),
    ):
        from synapsis.server import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/agents", {"name": "x", "description": "d", "system_prompt": "p"}),
    ("put", "/api/agents/my_custom_agent", {"description": "hijack"}),
    ("delete", "/api/agents/my_custom_agent", None),
    ("post", "/api/agents/data_analysis/clone", None),
    ("post", "/api/agents/data_analysis/test", {}),
])
async def test_agent_writes_are_admin_only(enforced_client, initialized_db: Path, method, path, body):
    await _insert_custom_agent(initialized_db)
    call = getattr(enforced_client, method)
    kwargs = {"headers": _bearer("researcher@cgiar.org", "researcher")}
    if body is not None:
        kwargs["json"] = body
    resp = await call(path, **kwargs)
    assert resp.status_code == 403
    # anonymous callers are not even authenticated
    anon_kwargs = {"json": body} if body is not None else {}
    assert (await call(path, **anon_kwargs)).status_code == 401


@pytest.mark.asyncio
async def test_admin_can_still_create_an_agent_record(enforced_client):
    resp = await enforced_client.post(
        "/api/agents",
        headers=_bearer("admin@cgiar.org", "admin"),
        json={"name": "Admin Agent", "description": "d", "system_prompt": "p"},
    )
    assert resp.status_code in (200, 201)


@pytest.mark.asyncio
async def test_researcher_can_read_personas_and_roster(enforced_client):
    headers = _bearer("researcher@cgiar.org", "researcher")
    personas = await enforced_client.get("/api/personas", headers=headers)
    assert personas.status_code == 200
    ids = {p["id"] for p in personas.json()["personas"]}
    assert "prms_data_analyst" in ids
    assert not ids & {"computer_use", "code_automation"}
    assert (await enforced_client.get("/api/agents", headers=headers)).status_code == 200
