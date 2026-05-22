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
    """GET /api/agents includes all 5 builtin agents and the orchestrator."""
    resp = await test_client.get("/api/agents")

    assert resp.status_code == 200
    data = resp.json()
    agent_ids = {a["id"] for a in data["agents"]}
    expected = {"data_analysis", "visualization_reporting", "research_methodology",
                "code_automation", "computer_use", "orchestrator"}
    assert expected.issubset(agent_ids), f"Missing agents: {expected - agent_ids}"


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
    resp = await test_client.delete("/api/agents/code_automation")

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
