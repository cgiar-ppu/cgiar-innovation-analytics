"""Deleting a chat while the idle/orphan reaper cleans the same client up must
not fail: ``cleanup_session_client`` is idempotent and safe to run twice at
the same time (DELETE /api/sessions/<id> used to answer HTTP 500 with a
KeyError when the reaper removed the entry during ``disconnect()``)."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from synapsis.session.client_registry import ClientRegistry  # noqa: E402


class SlowClient:
    """A client whose disconnect() waits until the test lets it finish."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.entered = asyncio.Event()
        self.disconnects = 0

    async def disconnect(self) -> None:
        self.disconnects += 1
        self.entered.set()
        await self.release.wait()


async def test_two_concurrent_cleanups_do_not_raise_and_disconnect_once():
    reg = ClientRegistry()
    client = SlowClient()
    reg.sessions["s1"] = client
    reg.touch("s1")

    first = asyncio.create_task(reg.cleanup_session_client("s1"))   # e.g. DELETE route
    await client.entered.wait()
    second = asyncio.create_task(reg.cleanup_session_client("s1"))  # e.g. orphan reaper
    await asyncio.sleep(0)
    client.release.set()
    await asyncio.gather(first, second)  # must not raise KeyError

    assert "s1" not in reg.sessions
    assert client.disconnects == 1
    assert "s1" not in reg._last_used and "s1" not in reg._session_locks


async def test_entry_removed_elsewhere_during_disconnect_is_tolerated():
    reg = ClientRegistry()
    client = SlowClient()
    reg.sessions["s2"] = client

    task = asyncio.create_task(reg.cleanup_session_client("s2"))
    await client.entered.wait()
    reg.sessions.pop("s2", None)  # another path removed it meanwhile
    client.release.set()
    await task  # must not raise

    assert "s2" not in reg.sessions


async def test_cleanup_of_unknown_session_is_a_no_op():
    reg = ClientRegistry()
    await reg.cleanup_session_client("never-existed")
    assert reg.sessions == {}


async def test_a_new_client_registered_during_disconnect_is_kept():
    """If the chat is reopened while the old client is still shutting down,
    the clean-up must not remove the NEW client."""
    reg = ClientRegistry()
    old = SlowClient()
    reg.sessions["s3"] = old

    task = asyncio.create_task(reg.cleanup_session_client("s3"))
    await old.entered.wait()
    new = object()
    reg.sessions["s3"] = new
    old.release.set()
    await task

    assert reg.sessions.get("s3") is new
