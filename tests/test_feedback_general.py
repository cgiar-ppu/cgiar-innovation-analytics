"""General "Give feedback" form (MVP test release item 1, 14 Oct 2026).

A category (stuck / wrong result / inappropriate-inaccurate / other), free text,
an optional PNG/JPEG screenshot (<= 5 MB, stored as a file, never in the row)
and server-derived context; administrators list, filter, view the screenshot
and export CSV / ZIP. The existing per-answer and voice ratings are unchanged.
"""
import csv
import io
import json
import time
import zipfile
from unittest.mock import patch

import aiosqlite
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from synapsis.auth.tokens import create_access_token

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def sso(user_id, role="researcher"):
    return {"Authorization": "Bearer " + create_access_token(user_id, user_id.split(":")[-1], role, auth_source="sso")}


ALICE, BOB, ADMIN = sso("sso:alice"), sso("sso:bob"), sso("sso:admin", "admin")


@pytest_asyncio.fixture
async def http(initialized_db, monkeypatch):
    import synapsis.config as config
    from synapsis.server import app
    monkeypatch.setenv("GIT_SHA", "abc1234")
    monkeypatch.setenv("IA_ENVIRONMENT", "dev")
    monkeypatch.setattr(config, "ENVIRONMENT_LABEL", "dev")
    monkeypatch.setattr(config, "SSO_ENABLED", True)
    monkeypatch.setattr(config, "INVITED_LOGIN_ENABLED", True)
    with (
        patch("synapsis.config.AUTH_DISABLED", False),
        patch("synapsis.auth.middleware.AUTH_DISABLED", False),
        patch("synapsis.database.DB_PATH", initialized_db),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            yield client


async def seed_chat(db_path, session_id="chat-a", owner="sso:alice", answers=2, model="claude-sonnet-5"):
    t = time.time() - 600
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(
            "INSERT INTO sessions (session_id, title, created_at, updated_at, model, user_id) VALUES (?,?,?,?,?,?)",
            (session_id, "t", t, t, model, owner))
        for i in range(1, answers + 1):
            meta = {"agent": "prms_data_analyst"} if i == 1 else {}
            for kind, data in (("user", {"content": f"Question {i}?", **meta}),
                               ("text", {"content": f"Answer {i}."}),
                               ("result", {"is_error": False})):
                t += 1
                await db.execute("INSERT INTO messages (session_id, ts, type, data) VALUES (?,?,?,?)",
                                 (session_id, t, kind, json.dumps(data)))
        await db.commit()


async def rows(db_path):
    async with aiosqlite.connect(str(db_path)) as db:
        db.row_factory = aiosqlite.Row
        return [dict(r) for r in await (await db.execute("SELECT * FROM answer_feedback ORDER BY id")).fetchall()]


def form(category="stuck", comment="I cannot find the export button", **extra):
    return {"category": category, "comment": comment, **extra}


# ---------------------------------------------------------------------------
# Schema / migration
# ---------------------------------------------------------------------------

async def test_new_columns_exist_and_old_databases_upgrade_in_place(initialized_db):
    from synapsis.database import feedback as store
    async with aiosqlite.connect(str(initialized_db)) as db:
        cols = {r[1] for r in await (await db.execute("PRAGMA table_info(answer_feedback)")).fetchall()}
    assert {"category", "attachment_path", "page", "chat_id", "answer_id"} <= cols
    assert store.MIGRATION_NAME == "answer_feedback_general_v1"

    # A database created by the previous release (no new columns, one chat rating).
    async with aiosqlite.connect(str(initialized_db)) as db:
        await db.execute("DROP TABLE answer_feedback")
        await db.execute(store._SCHEMA[0])
        await db.execute(
            "INSERT INTO answer_feedback (user_id, channel, session_id, message_id, rating, created_at, updated_at) "
            "VALUES ('sso:alice', 'chat', 'chat-a', 'r1', 1, 1, 1)")
        await db.commit()
    store._READY_PATHS.clear()
    await store.init_feedback_table()
    await store.init_feedback_table()  # idempotent
    stored = await rows(initialized_db)
    assert len(stored) == 1 and stored[0]["category"] == "" and stored[0]["attachment_path"] == ""


# ---------------------------------------------------------------------------
# Submitting
# ---------------------------------------------------------------------------

async def test_general_feedback_with_screenshot_and_context(http, initialized_db):
    await seed_chat(initialized_db)
    r = await http.post("/api/feedback/general", headers=ALICE,
                        data=form("wrong_result", "  The 2025 count looks too low.  ", page="/chat/chat-a?x=1",
                                  chat_id="chat-a", answer_id="r1"),
                        files={"screenshot": ("paste.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["channel"] == "general" and body["category"] == "wrong_result" and body["has_attachment"] is True
    assert body["chat_id"] == "chat-a" and body["answer_id"] == "r1" and body["page"] == "/chat/chat-a"

    (row,) = await rows(initialized_db)
    assert row["channel"] == "general" and row["rating"] == 0 and row["message_id"] == ""
    assert row["session_id"].startswith("g-")
    assert row["comment"] == "The 2025 count looks too low."
    assert (row["role"], row["environment"], row["app_version"]) == ("researcher", "dev", "abc1234")
    assert row["model"] == "claude-sonnet-5" and row["persona"] == "prms_data_analyst"
    assert row["shared_question"] is None and row["shared_answer"] is None, "never chat text"
    # The row stores a relative path; the bytes are in a file next to the database.
    assert row["attachment_path"].startswith("feedback-attachments/") and row["attachment_path"].endswith(".png")
    assert (initialized_db.parent / row["attachment_path"]).read_bytes() == PNG
    assert not any(isinstance(v, bytes) for v in row.values())


async def test_every_submission_is_a_new_row_and_jpeg_is_accepted(http, initialized_db):
    for category in ("stuck", "wrong_result", "inappropriate_inaccurate", "other"):
        assert (await http.post("/api/feedback/general", headers=ALICE, data=form(category))).status_code == 200
    r = await http.post("/api/feedback/general", headers=ALICE, data=form("other", ""),
                        files={"screenshot": ("shot.jpg", JPG, "image/jpeg")})
    assert r.status_code == 200, r.text
    stored = await rows(initialized_db)
    assert [s["category"] for s in stored] == ["stuck", "wrong_result", "inappropriate_inaccurate", "other", "other"]
    assert stored[-1]["attachment_path"].endswith(".jpg") and stored[-1]["comment"] == ""


@pytest.mark.parametrize("data,files,status", [
    (form("broken"), None, 422),                                   # unknown category
    ({"comment": "x"}, None, 422),                                 # no category
    (form(comment="   "), None, 422),                              # neither text nor screenshot
    (form(), {"screenshot": ("a.gif", b"GIF89a" + b"\0" * 20, "image/gif")}, 415),
    (form(), {"screenshot": ("a.png", b"<svg onload=alert(1)>", "image/png")}, 415),   # type is sniffed, not trusted
    (form(), {"screenshot": ("a.txt", b"hello", "text/plain")}, 415),
    (form(comment="x" * 4001), None, 422),
])
async def test_invalid_general_feedback_is_rejected(http, initialized_db, data, files, status):
    r = await http.post("/api/feedback/general", headers=ALICE, data=data, files=files)
    assert r.status_code == status, r.text
    assert await rows(initialized_db) == []
    folder = initialized_db.parent / "feedback-attachments"
    assert not folder.exists() or not any(folder.iterdir()), "rejected uploads leave no file"


async def test_screenshot_over_5_mb_is_rejected(http, initialized_db):
    big = PNG + b"\0" * (5 * 1024 * 1024)
    r = await http.post("/api/feedback/general", headers=ALICE, data=form(),
                        files={"screenshot": ("big.png", big, "image/png")})
    assert r.status_code == 413
    assert await rows(initialized_db) == []
    exact = PNG + b"\0" * (5 * 1024 * 1024 - len(PNG))
    r = await http.post("/api/feedback/general", headers=ALICE, data=form(),
                        files={"screenshot": ("max.png", exact, "image/png")})
    assert r.status_code == 200, "exactly 5 MB is allowed"


async def test_foreign_or_unknown_chat_ids_are_dropped_not_stored(http, initialized_db):
    await seed_chat(initialized_db, session_id="chat-b", owner="sso:bob", answers=1)
    r = await http.post("/api/feedback/general", headers=ALICE,
                        data=form(chat_id="chat-b", answer_id="r1", page="javascript:alert(1)"))
    assert r.status_code == 200
    r = await http.post("/api/feedback/general", headers=ALICE, data=form(chat_id="nope", answer_id="r9"))
    assert r.status_code == 200
    for row in await rows(initialized_db):
        assert (row["chat_id"], row["answer_id"], row["model"], row["page"]) == ("", "", "", "")


async def test_general_feedback_needs_sign_in_and_is_rate_limited(http, initialized_db, monkeypatch):
    assert (await http.post("/api/feedback/general", data=form())).status_code == 401
    import synapsis.routes.feedback as routes
    monkeypatch.setattr(routes, "GENERAL_PER_HOUR", 2)
    assert (await http.post("/api/feedback/general", headers=ALICE, data=form())).status_code == 200
    assert (await http.post("/api/feedback/general", headers=ALICE, data=form())).status_code == 200
    assert (await http.post("/api/feedback/general", headers=ALICE, data=form())).status_code == 429
    assert (await http.post("/api/feedback/general", headers=BOB, data=form())).status_code == 200


async def test_json_post_accepts_general_channel_without_screenshot(http, initialized_db):
    r = await http.post("/api/feedback", headers=ALICE, json={
        "channel": "general", "category": "inappropriate_inaccurate", "comment": "Tone is off", "page": "/"})
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "inappropriate_inaccurate"
    for bad in ({"channel": "general", "comment": "x"},                                   # no category
                {"channel": "general", "category": "stuck"},                              # no text
                {"channel": "general", "category": "stuck", "comment": "x", "rating": 1},
                {"channel": "general", "category": "stuck", "comment": "x", "share_answer": True},
                {"channel": "chat", "session_id": "c", "message_id": "r1", "rating": 1, "category": "stuck"}):
        assert (await http.post("/api/feedback", headers=ALICE, json=bad)).status_code == 422, bad


async def test_withdrawing_general_feedback_removes_the_screenshot(http, initialized_db):
    saved = (await http.post("/api/feedback/general", headers=ALICE, data=form(),
                             files={"screenshot": ("a.png", PNG, "image/png")})).json()
    (row,) = await rows(initialized_db)
    path = initialized_db.parent / row["attachment_path"]
    assert path.exists()
    assert (await http.delete(f"/api/feedback/{saved['id']}", headers=BOB)).status_code == 404
    assert path.exists()
    assert (await http.delete(f"/api/feedback/{saved['id']}", headers=ALICE)).status_code == 200
    assert not path.exists() and await rows(initialized_db) == []


# ---------------------------------------------------------------------------
# Existing ratings keep working next to general feedback
# ---------------------------------------------------------------------------

async def test_answer_and_voice_ratings_are_unchanged(http, initialized_db):
    await seed_chat(initialized_db)
    assert (await http.post("/api/feedback/general", headers=ALICE, data=form(chat_id="chat-a", answer_id="r1"))).status_code == 200
    r = await http.post("/api/feedback", headers=ALICE, json={"session_id": "chat-a", "message_id": "r1", "rating": -1})
    assert r.status_code == 200 and "category" not in r.json()
    mine = (await http.get("/api/feedback?session_id=chat-a", headers=ALICE)).json()["feedback"]
    assert [(f["channel"], f["message_id"], f["rating"]) for f in mine] == [("chat", "r1", -1)]
    # Old validation still applies to chat ratings.
    for bad in ({"session_id": "chat-a", "message_id": "r1"},                  # rating missing
                {"session_id": "chat-a", "message_id": "r1", "rating": 2},
                {"session_id": "chat-a", "message_id": "r1", "rating": 1, "comment": "x" * 2001},
                {"message_id": "r1", "rating": 1}):
        assert (await http.post("/api/feedback", headers=ALICE, json=bad)).status_code == 422, bad


# ---------------------------------------------------------------------------
# Kill-switch
# ---------------------------------------------------------------------------

async def test_kill_switch_turns_off_general_feedback_and_screenshots(http, initialized_db, monkeypatch):
    saved = (await http.post("/api/feedback/general", headers=ALICE, data=form(),
                             files={"screenshot": ("a.png", PNG, "image/png")})).json()
    assert (await http.get("/api/config", headers=ALICE)).json()["feedback_enabled"] is True
    monkeypatch.setenv("IA_FEEDBACK_ENABLED", "false")
    assert (await http.post("/api/feedback/general", headers=ALICE, data=form())).status_code == 404
    assert (await http.post("/api/feedback", headers=ALICE, json={
        "channel": "general", "category": "stuck", "comment": "x"})).status_code == 404
    assert (await http.get(f"/api/admin/feedback/{saved['id']}/attachment", headers=ADMIN)).status_code == 404
    assert (await http.get("/api/admin/feedback?format=zip", headers=ADMIN)).status_code == 404
    assert (await http.get("/api/config", headers=ALICE)).json()["feedback_enabled"] is False
    assert len(await rows(initialized_db)) == 1


# ---------------------------------------------------------------------------
# Admin review
# ---------------------------------------------------------------------------

async def test_admin_list_csv_zip_and_screenshot(http, initialized_db):
    await seed_chat(initialized_db)
    await http.post("/api/feedback", headers=ALICE, json={"session_id": "chat-a", "message_id": "r1", "rating": 1})
    shot = (await http.post("/api/feedback/general", headers=ALICE,
                            data=form("wrong_result", "=cmd|' /C calc'!A0", page="/", chat_id="chat-a", answer_id="r2"),
                            files={"screenshot": ("a.png", PNG, "image/png")})).json()
    await http.post("/api/feedback/general", headers=BOB, data=form("stuck", "Lost on the dashboard", page="/"))

    body = (await http.get("/api/admin/feedback", headers=ADMIN)).json()
    assert body["total"] == 3
    assert body["counts"] == {"positive": 1, "negative": 0, "neutral": 0}, "general rows carry no rating"
    assert body["by_category"] == {"stuck": 1, "wrong_result": 1, "inappropriate_inaccurate": 0, "other": 0}
    item = next(i for i in body["items"] if i["id"] == shot["id"])
    assert item["channel"] == "general" and item["sentiment"] == ""
    assert item["category"] == "wrong_result" and item["category_label"] == "This result looks wrong"
    assert (item["page"], item["chat_id"], item["answer_id"]) == ("/", "chat-a", "r2")
    assert item["has_attachment"] is True and item["attachment_type"] == "png"
    assert item["attachment_url"] == f"/api/admin/feedback/{shot['id']}/attachment"
    assert "feedback-attachments" not in json.dumps(body), "the storage path is not exposed"

    general = (await http.get("/api/admin/feedback?channel=general", headers=ADMIN)).json()
    assert general["total"] == 2
    stuck = (await http.get("/api/admin/feedback?category=stuck", headers=ADMIN)).json()
    assert [i["comment"] for i in stuck["items"]] == ["Lost on the dashboard"]
    assert (await http.get("/api/admin/feedback?category=bad", headers=ADMIN)).status_code == 422
    assert (await http.get("/api/admin/feedback?rating=negative", headers=ADMIN)).json()["total"] == 0

    # Screenshot: admin only, inline image, sandboxed.
    url = item["attachment_url"]
    assert (await http.get(url)).status_code == 401
    assert (await http.get(url, headers=ALICE)).status_code == 403
    r = await http.get(url, headers=ADMIN)
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png" and r.headers["content-disposition"].startswith("inline")
    assert "sandbox" in r.headers["content-security-policy"] and r.headers["x-content-type-options"] == "nosniff"
    no_shot = next(i for i in body["items"] if i["channel"] == "general" and i["id"] != shot["id"])
    assert (await http.get(f"/api/admin/feedback/{no_shot['id']}/attachment", headers=ADMIN)).status_code == 404
    assert (await http.get("/api/admin/feedback/99999/attachment", headers=ADMIN)).status_code == 404

    # CSV: new columns, screenshot link, formulas neutralised.
    r = await http.get("/api/admin/feedback?format=csv", headers=ADMIN)
    table = list(csv.DictReader(io.StringIO(r.text.lstrip("﻿"))))
    assert {"category", "page", "chat_id", "answer_id", "screenshot", "id"} <= set(table[0])
    row = next(t for t in table if t["id"] == str(shot["id"]))
    assert row["category"] == "This result looks wrong" and row["screenshot"] == url
    assert row["comment"].startswith("'="), "spreadsheet formulas are neutralised"
    assert row["chat_id"] == "chat-a" and row["answer_id"] == "r2" and row["channel"] == "general"

    # ZIP: the CSV plus the screenshot files it names.
    r = await http.get("/api/admin/feedback?format=zip", headers=ADMIN)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"].startswith('attachment; filename="ia-feedback-dev-')
    archive = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(archive.namelist()) == ["feedback.csv", f"screenshots/feedback-{shot['id']}.png"]
    assert archive.read(f"screenshots/feedback-{shot['id']}.png") == PNG
    zipped = list(csv.DictReader(io.StringIO(archive.read("feedback.csv").decode("utf-8-sig"))))
    assert next(t for t in zipped if t["id"] == str(shot["id"]))["screenshot"] == f"screenshots/feedback-{shot['id']}.png"
    assert (await http.get("/api/admin/feedback?format=zip", headers=ALICE)).status_code == 403


async def test_screenshots_are_never_served_by_the_files_api(http, initialized_db):
    await http.post("/api/feedback/general", headers=ALICE, data=form(),
                    files={"screenshot": ("a.png", PNG, "image/png")})
    (row,) = await rows(initialized_db)
    listed = (await http.get("/api/files", headers=ADMIN)).json()["files"]
    assert not any("feedback-attachments" in f["name"] for f in listed)
    r = await http.get("/api/files/.synapsis/" + row["attachment_path"], headers=ADMIN)
    assert r.status_code in (403, 404)
