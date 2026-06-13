"""
Client registry -- SDK client lifecycle and per-session locking.

Manages the ``sessions`` dict (app session_id -> connected ClaudeSDKClient),
per-session locks to prevent concurrent queries, and helper methods that
create, resume, and tear down SDK clients.

Safety guardrails (added to prevent runaway subprocess storms):
- Max concurrent session limit (configurable, default 10)
- Rate limiting on new session creation (max 5 per 60s by default)
- Idle session eviction when limit is reached
- Background reaper for orphaned sessions
"""

import asyncio
import time
import uuid
from collections import deque
from typing import Optional

from claude_agent_sdk import ClaudeSDKClient

from synapsis.config import logger, MAX_SESSIONS
from synapsis.constants import (
    SESSION_ID_LENGTH,
    SESSION_TITLE_PREVIEW_LENGTH,
    SESSION_CREATION_RATE_WINDOW,
    SESSION_CREATION_RATE_LIMIT,
)
from synapsis.database import create_session, get_claude_session_id, get_session_model
from synapsis.agent_options import build_agent_options
from synapsis.session.client_factory import create_client_with_retry


class ClientRegistry:
    """Owns the sessions dict, per-session locks, and client lifecycle."""

    def __init__(self) -> None:
        # Active sessions: app session_id -> connected ClaudeSDKClient
        self.sessions: dict[str, ClaudeSDKClient] = {}

        # Per-session locks to prevent concurrent queries on the same SDK client.
        self._session_locks: dict[str, asyncio.Lock] = {}

        # Rate limiter: timestamps of recent session creations (sliding window)
        self._creation_timestamps: deque[float] = deque()

    # -------------------------------------------------------------------
    # Client health check
    # -------------------------------------------------------------------

    @staticmethod
    def _is_client_alive(client: ClaudeSDKClient) -> bool:
        """Check whether a cached SDK client's subprocess is still running.

        The Claude Agent SDK spawns a ``claude`` CLI subprocess per client.
        If that process has exited (e.g. due to a server restart, idle
        timeout, or crash), ``client.query()`` will raise CLIConnectionError
        ("Cannot write to terminated process").  This helper detects that
        condition early so callers can discard the dead client and create a
        fresh one via the resume path.

        Returns True if the subprocess appears alive (or if we cannot
        inspect it), False if it has definitely exited.
        """
        try:
            # The SDK stores the subprocess in client._transport._process
            # (SubprocessCLITransport).  If the process has exited,
            # returncode is not None.
            transport = getattr(client, "_transport", None)
            if transport is None:
                return True  # Cannot inspect -- assume alive
            process = getattr(transport, "_process", None)
            if process is None:
                return True  # No subprocess yet -- assume alive
            if process.returncode is not None:
                return False  # Subprocess has exited
            return True
        except Exception:
            # Any introspection failure -- assume alive and let query()
            # surface the real error if the client is truly dead.
            return True

    # -------------------------------------------------------------------
    # Session creation guardrails
    # -------------------------------------------------------------------

    def _check_rate_limit(self) -> None:
        """Raise RuntimeError if session creation rate limit is exceeded.

        Uses a sliding window: removes timestamps older than the window,
        then checks if the count exceeds the limit.
        """
        now = time.monotonic()
        cutoff = now - SESSION_CREATION_RATE_WINDOW
        while self._creation_timestamps and self._creation_timestamps[0] < cutoff:
            self._creation_timestamps.popleft()
        if len(self._creation_timestamps) >= SESSION_CREATION_RATE_LIMIT:
            logger.warning(
                "Session creation rate limit exceeded: %d sessions in last %ds "
                "(limit: %d). Rejecting new session.",
                len(self._creation_timestamps),
                SESSION_CREATION_RATE_WINDOW,
                SESSION_CREATION_RATE_LIMIT,
            )
            raise RuntimeError(
                f"Too many sessions created recently ({SESSION_CREATION_RATE_LIMIT} "
                f"in {SESSION_CREATION_RATE_WINDOW}s). Please wait before creating "
                f"new sessions."
            )

    def _record_creation(self) -> None:
        """Record a session creation timestamp for rate limiting."""
        self._creation_timestamps.append(time.monotonic())

    async def _evict_idle_sessions(self) -> int:
        """Evict idle sessions (not busy) to make room for new ones.

        Returns the number of sessions evicted.
        """
        evicted = 0
        # Build a list of candidates: sessions that are NOT busy (lock not held)
        candidates = [
            sid for sid in list(self.sessions)
            if not self.is_session_busy(sid)
        ]
        for sid in candidates:
            if len(self.sessions) < MAX_SESSIONS:
                break  # We have room now
            logger.info("Evicting idle session %s to make room (at limit %d)", sid, MAX_SESSIONS)
            await self.cleanup_session_client(sid)
            evicted += 1
        return evicted

    async def _ensure_session_capacity(self) -> None:
        """Ensure there is room for a new session.

        First tries to evict idle sessions. If still at capacity (all sessions
        are busy), raises RuntimeError.
        """
        if len(self.sessions) < MAX_SESSIONS:
            return  # Room available

        evicted = await self._evict_idle_sessions()
        if evicted > 0:
            logger.info("Evicted %d idle session(s) to stay under limit %d", evicted, MAX_SESSIONS)
            return

        # All sessions are busy — cannot evict any
        logger.error(
            "Max concurrent sessions reached (%d) and all are busy. "
            "Rejecting new session.",
            MAX_SESSIONS,
        )
        raise RuntimeError(
            f"Maximum concurrent sessions ({MAX_SESSIONS}) reached and all are "
            f"active. Please close an existing session first."
        )

    # -------------------------------------------------------------------
    # Client factory
    # -------------------------------------------------------------------

    async def _create_and_connect_client(
        self,
        resume_session_id: Optional[str] = None,
        model: Optional[str] = None,
    ) -> ClaudeSDKClient:
        """Build agent options, create a ClaudeSDKClient, and connect it.

        Args:
            resume_session_id: If provided, the Claude SDK session UUID to resume.
                               Pass None or empty string to start a fresh session.
            model:             Optional model ID override for this client. Pass
                               None or empty string to use the server default.

        Returns:
            A connected ClaudeSDKClient ready to receive queries.
        """
        options = await build_agent_options(
            resume_session_id=resume_session_id,
            model_override=model or None,
        )
        return await create_client_with_retry(
            options,
            max_retries=2,
            retry_delay=1.0,
            resume_session_id=resume_session_id,
        )

    # -------------------------------------------------------------------
    # Per-session lock helpers
    # -------------------------------------------------------------------

    def get_session_lock(self, session_id: str) -> asyncio.Lock:
        """Get or create a lock for a session.

        Ensures only one WebSocket connection queries a given session's SDK
        client at a time.  Multiple calls with the same session_id always
        return the same Lock object.
        """
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]

    async def acquire_session_client(
        self,
        session_id: str,
        sessions_dict: dict,
    ) -> tuple["ClaudeSDKClient", bool]:
        """Acquire a session's SDK client for exclusive use.

        The ChatRunManager cancels any existing task before starting a new one,
        so the lock will always be free when this method is called.  This method
        waits for the lock and returns the shared client.

        Args:
            session_id:    The app session ID to acquire.
            sessions_dict: The live sessions mapping (typically ``self.sessions``).

        Returns:
            (client, lock_acquired) -- lock_acquired is always True.

        Raises:
            KeyError: If the session is not found in sessions_dict.
        """
        lock = self.get_session_lock(session_id)
        await lock.acquire()
        client = sessions_dict.get(session_id)
        if not client:
            lock.release()
            raise KeyError(f"Session {session_id} not found")
        return client, True

    def release_session_client(self, session_id: str) -> None:
        """Release a session's lock after streaming is complete.

        Safe to call even if no lock exists or the lock is not currently held.
        Also prunes the lock from _session_locks if the session is no longer
        in memory (prevents unbounded growth of stale lock objects).
        """
        lock = self._session_locks.get(session_id)
        if lock and lock.locked():
            lock.release()
        # Prune stale lock if session is no longer in memory and lock is free
        if session_id not in self.sessions and session_id in self._session_locks:
            lk = self._session_locks[session_id]
            if not lk.locked():
                self._session_locks.pop(session_id, None)

    def is_session_busy(self, session_id: str) -> bool:
        """Check whether a session currently has an active streaming task.

        Returns True if the per-session lock exists and is held, meaning
        another connection is actively streaming a response for this session.
        """
        lock = self._session_locks.get(session_id)
        return bool(lock and lock.locked())

    def cleanup_done_tasks(self, *args, **kwargs) -> None:
        """No-op -- the ChatRunManager handles task lifecycle now.

        Kept for backward compatibility with callers that may still invoke it.
        """
        pass

    # -------------------------------------------------------------------
    # Session lifecycle
    # -------------------------------------------------------------------

    async def _resume_or_create_client(
        self,
        session_id: str,
        sessions_dict: dict,
    ) -> ClaudeSDKClient:
        """Look up a session's Claude SDK UUID in the DB and connect a client.

        If a stored ``claude_session_id`` exists, resumes from it; otherwise
        creates a fresh client.  After connecting with resume, waits briefly
        and verifies the subprocess is still alive — some corrupted sessions
        cause the CLI to crash within ~1 second of resuming.  If the resumed
        client dies, falls back to a fresh session so the user can continue
        (conversation history is preserved in the DB even though the CLI
        loses its context).

        The resulting client is stored into *sessions_dict* before returning.

        This is the shared implementation behind both ``handle_switch_session``
        (slow path) and ``ensure_session`` (case 2).
        """
        claude_sid = await get_claude_session_id(session_id)
        # Use the session's persisted model so resumed clients keep the model
        # the user selected for this chat (falls back to server default if "").
        model = await get_session_model(session_id)
        client = await self._create_and_connect_client(
            resume_session_id=claude_sid, model=model or None,
        )

        if claude_sid:
            # Post-connect health check: some sessions are corrupted and cause
            # the CLI subprocess to crash within ~1s of resuming.  Wait briefly
            # and verify the process is still alive before returning.
            await asyncio.sleep(1.0)
            if not self._is_client_alive(client):
                logger.warning(
                    "Resumed client for session %s died immediately after connect "
                    "(Claude session %s is likely corrupted) — falling back to fresh session",
                    session_id, claude_sid,
                )
                client = await self._create_and_connect_client(
                    resume_session_id=None, model=model or None,
                )
                logger.info(
                    "Fresh fallback client created for session %s (history preserved in DB, "
                    "but Claude context reset)",
                    session_id,
                )
            else:
                logger.info("Resumed session %s with Claude session %s", session_id, claude_sid)
        else:
            logger.info("No Claude session UUID for %s -- starting fresh", session_id)

        sessions_dict[session_id] = client
        return client

    async def cleanup_session_client(self, session_id: str) -> None:
        """Disconnect and remove a session's SDK client.

        Called externally (e.g. when the user deletes a session via the REST
        API) so the SDK connection is cleaned up gracefully. Also removes any
        lock associated with the session.
        """
        if session_id in self.sessions:
            try:
                await self.sessions[session_id].disconnect()
            except Exception:
                # SDK disconnect may raise anything; ignore on teardown
                pass
            del self.sessions[session_id]
        # Release and remove the per-session lock so it does not linger.
        self.release_session_client(session_id)
        self._session_locks.pop(session_id, None)

    async def handle_new_session(
        self,
        sessions_dict: dict,
        send_json,
    ) -> tuple[str, ClaudeSDKClient]:
        """Create a brand-new session and return (session_id, client).

        Inserts a DB row, creates a fresh SDK client, and notifies the caller
        via send_json so the frontend can update its session state.

        Raises RuntimeError if rate limit or capacity limit is exceeded.
        """
        self._check_rate_limit()
        await self._ensure_session_capacity()

        session_id = str(uuid.uuid4())[:SESSION_ID_LENGTH]
        await create_session(session_id)
        client = await self._create_and_connect_client()
        sessions_dict[session_id] = client
        self._record_creation()
        await send_json({"type": "session", "session_id": session_id}, sid=session_id)
        return session_id, client

    async def handle_switch_session(
        self,
        payload: dict,
        sessions_dict: dict,
        send_json,
    ) -> Optional[tuple[str, ClaudeSDKClient]]:
        """Switch the connection's active session.

        If the session is already in memory, it is reused directly. Otherwise
        the session is looked up in the database and resumed (with the stored
        Claude session UUID if available, or fresh if not).

        Returns:
            (session_id, client) on success, or None if payload has no session_id.
        """
        requested_sid = payload.get("session_id", "")
        if not requested_sid:
            return None

        # Fast path: client already in memory — verify subprocess is alive
        if requested_sid in sessions_dict:
            client = sessions_dict[requested_sid]
            if self._is_client_alive(client):
                busy = self.is_session_busy(requested_sid)
                await send_json(
                    {"type": "session", "session_id": requested_sid, "is_busy": busy},
                    sid=requested_sid,
                )
                return requested_sid, client
            # Subprocess died — discard and fall through to the slow (resume) path
            logger.warning(
                "Stale client detected on switch_session for %s — recreating via resume",
                requested_sid,
            )
            del sessions_dict[requested_sid]

        # Slow path: session exists in DB but not in memory -- resume from stored UUID
        client = await self._resume_or_create_client(requested_sid, sessions_dict)

        await send_json(
            {"type": "session", "session_id": requested_sid, "is_busy": False},
            sid=requested_sid,
        )
        return requested_sid, client

    async def ensure_session(
        self,
        session_id: Optional[str],
        user_message: str,
        sessions_dict: dict,
    ) -> tuple[str, ClaudeSDKClient]:
        """Ensure a valid session and connected client exist before sending a message.

        Handles three cases:
        1. Session and client already in memory -- reuse directly.
        2. Session exists (e.g. post-cancel) but client was removed -- recreate with resume.
        3. No session at all -- create a brand-new session and client.

        Args:
            session_id:    The current session ID, or None if none has been established.
            user_message:  The user's message (used as the session title on creation).
            sessions_dict: The live sessions mapping to check/update.

        Returns:
            (session_id, client) -- always valid on return.
        """
        # Case 1: everything already available — but verify the subprocess is alive
        if session_id and session_id in sessions_dict:
            client = sessions_dict[session_id]
            if self._is_client_alive(client):
                return session_id, client
            # Subprocess died — discard the dead client and fall through to Case 2
            # which will look up the claude_session_id from the DB and resume.
            logger.warning(
                "Stale client detected for session %s — subprocess exited, "
                "discarding and recreating via resume",
                session_id,
            )
            del sessions_dict[session_id]

        # Case 2: session exists but client was dropped (e.g. after a cancel)
        if session_id:
            client = await self._resume_or_create_client(session_id, sessions_dict)
            return session_id, client

        # Case 3: no session -- create one, using the first message as the title
        self._check_rate_limit()
        await self._ensure_session_capacity()

        session_id = str(uuid.uuid4())[:SESSION_ID_LENGTH]
        await create_session(session_id, title=user_message[:SESSION_TITLE_PREVIEW_LENGTH])
        client = await self._create_and_connect_client()
        sessions_dict[session_id] = client
        self._record_creation()
        logger.info("New session %s", session_id)
        return session_id, client
