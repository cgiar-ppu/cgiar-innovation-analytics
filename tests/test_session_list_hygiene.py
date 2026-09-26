"""QA-4 D11 / D12: the chat list never shows the attached-files preamble or a
server path as a title, and never-used (empty) chats are hidden, not deleted."""

from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from synapsis.routes.sessions import title_text

UPLOAD = (
    "[Attached files]\n"
    "  qa4-pilot-sites.xlsx -> /workspace/uploads/u/ab12cd/qa4-pilot-sites.xlsx\n"
    "[End attached files]\n\n"
)


def _token(user_id: str, role: str = "researcher") -> str:
    from synapsis.auth.tokens import create_access_token
    return create_access_token(user_id, user_id.split("@")[0], role)


@pytest.mark.parametrize("content,expected", [
    (UPLOAD + "Which site has the highest adoption?", "Which site has the highest adoption?"),
    (UPLOAD.strip(), "Attached: qa4-pilot-sites.xlsx"),
    ("[Attached files]\n  a.csv -> /workspace/uploads/u/x/a.csv\n  b.docx -> /workspace/uploads/u/x/b.docx\n"
     "[End attached files]\n", "Attached: a.csv, b.docx"),
    ("Plain question", "Plain question"),
    ("", ""),
])
def test_title_text(content, expected):
    out = title_text(content)
    assert out == expected
    assert "/workspace" not in out and "[Attached files]" not in out


@pytest_asyncio.fixture
async def client(initialized_db):
    from synapsis.database import create_session, save_message

    await create_session("s-used", title="", user_id="alice@cgiar.org")
    await save_message("s-used", "user", {"content": UPLOAD + "Which site has the highest adoption?"})
    await create_session("s-upload-only", title="", user_id="alice@cgiar.org")
    await save_message("s-upload-only", "user", {"content": UPLOAD.strip()})
    await create_session("s-empty", title="", user_id="alice@cgiar.org")
    await create_session("s-empty-active", title="", user_id="alice@cgiar.org")
    await create_session("s-empty-renamed", title="Planning", user_id="alice@cgiar.org")
    with (
        patch("synapsis.config.AUTH_DISABLED", False),
        patch("synapsis.auth.middleware.AUTH_DISABLED", False),
    ):
        from synapsis.server import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_fallback_titles_never_show_the_preamble_or_path(client):
    h = {"Authorization": f"Bearer {_token('alice@cgiar.org')}"}
    sessions = {s["session_id"]: s for s in (await client.get("/api/sessions", headers=h)).json()["sessions"]}
    assert sessions["s-used"]["title"] == "Which site has the highest adoption?"
    assert sessions["s-upload-only"]["title"] == "Attached: qa4-pilot-sites.xlsx"
    for s in sessions.values():
        assert "/workspace" not in (s["title"] or "") and "[Attached" not in (s["title"] or "")


@pytest.mark.asyncio
async def test_auto_title_strips_the_preamble(client):
    h = {"Authorization": f"Bearer {_token('alice@cgiar.org')}"}
    r = await client.post("/api/sessions/s-used/auto-title", headers=h)
    assert r.status_code == 200
    assert r.json()["title"] == "Which site has the highest adoption?"


@pytest.mark.asyncio
async def test_empty_chats_are_hidden_but_kept(client):
    from synapsis.database import get_session_owner

    h = {"Authorization": f"Bearer {_token('alice@cgiar.org')}"}
    ids = [s["session_id"] for s in (await client.get("/api/sessions", headers=h)).json()["sessions"]]
    assert "s-empty" not in ids and "s-empty-active" not in ids
    assert {"s-used", "s-upload-only", "s-empty-renamed"} <= set(ids)
    # The client's active (still empty) chat stays visible when asked for.
    ids = [s["session_id"] for s in
           (await client.get("/api/sessions?keep=s-empty-active", headers=h)).json()["sessions"]]
    assert "s-empty-active" in ids and "s-empty" not in ids
    # Hidden, not deleted.
    assert await get_session_owner("s-empty") == "alice@cgiar.org"


@pytest.mark.asyncio
async def test_keep_cannot_reveal_another_users_chat(client):
    from synapsis.database import create_session

    await create_session("s-bob-empty", title="", user_id="bob@cgiar.org")
    h = {"Authorization": f"Bearer {_token('alice@cgiar.org')}"}
    ids = [s["session_id"] for s in
           (await client.get("/api/sessions?keep=s-bob-empty", headers=h)).json()["sessions"]]
    assert "s-bob-empty" not in ids
