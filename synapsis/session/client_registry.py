"""
Client registry -- SDK client lifecycle and per-session locking.

Manages the ``sessions`` dict (app session_id -> connected ClaudeSDKClient),
per-session locks to prevent concurrent queries, and helper methods that
create, resume, and tear down SDK clients.

Safety guardrails (added to prevent runaway subprocess storms):
- Max concurrent live CLI clients (configurable, default 10), enforced for new
  chats AND for resumed chats (L3-04); idle clients are evicted least-recently
  used first when the limit is reached
- Per-user rate limit on new chats (5 per 60s by default) plus a
  deployment-wide safety net (30 per 60s) (L3-03)
- Lazy CLI start: "New chat" and opening an old chat only create/select the
  DB row; the CLI subprocess starts when the first message is sent
- Background reaper for orphaned sessions

Limit violations raise :class:`synapsis.runtime_policy.SessionLimitError`
(a RuntimeError) carrying a friendly English message; the WebSocket handler
turns it into an error frame and keeps the connection open.
"""

import asyncio
import time
import uuid
from collections import deque
from typing import Optional

from claude_agent_sdk import ClaudeSDKClient

import synapsis.config as _config
from synapsis.config import logger, MAX_SESSIONS
from synapsis.constants import (
    SESSION_ID_LENGTH,
    SESSION_TITLE_PREVIEW_LENGTH,
    CAPACITY_ERROR,
    GLOBAL_RATE_LIMIT_ERROR,
    NEW_CHAT_RATE_LIMIT_ERROR,
)
from synapsis.database import create_session, get_claude_session_id, get_session_model
from synapsis.agent_options import build_agent_options
from synapsis.runtime_policy import (
    SessionLimitError,
    current_user_id,
    resolve_model,
    turn_budget_usd,
)
from synapsis.session.client_factory import create_client_with_retry


def tag_client(
    client,
    *,
    cost_baseline: float = 0.0,
    model: Optional[str] = None,
    budget_usd: Optional[float] = None,
) -> None:
    """Attach the runtime-accounting attributes stream_handler relies on.

    ``_ia_cost_baseline``  SDK running total after the previous question
                           (resumed CLIs restore the conversation's total)
    ``_ia_spent``          spend since this CLI process started (what the
                           CLI's ``max_budget_usd`` counts)
    ``_ia_budget``         the per-question ceiling the process was started with
    ``_ia_recycle``        set when the process should be replaced before the
                           next question (budget headroom used up / stalled)
    """
    try:
        client._ia_cost_baseline = float(cost_baseline or 0.0)
        client._ia_spent = 0.0
        client._ia_budget = budget_usd
        client._ia_model = model
        client._ia_recycle = False
    except Exception:  # pragma: no cover - exotic client objects
        logger.debug("Could not tag client for accounting", exc_info=True)


class ClientRegistry:
    """Owns the sessions dict, per-session locks, and client lifecycle."""

    def __init__(self) -> None:
        # Active sessions: app session_id -> connected ClaudeSDKClient
        self.sessions: dict[str, ClaudeSDKClient] = {}

        # Per-session locks to prevent concurrent queries on the same SDK client.
        self._session_locks: dict[str, asyncio.Lock] = {}

        # Rate limiter: per-user timestamps of recent chat creations (sliding
        # window) + one deployment-wide window as a storm safety net.
        self._creation_timestamps: dict[str, deque[float]] = {}
        self._global_creations: deque[float] = deque()

        # LRU bookkeeping for eviction: session_id -> last time it was used.
        self._last_used: dict[str, float] = {}

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

    @staticmethod
    def _prune(window: deque, cutoff: float) -> None:
        while window and window[0] < cutoff:
            window.popleft()

    def _check_rate_limit(self, user_id: Optional[str] = None) -> None:
        """Raise SessionLimitError if this user (or everyone together) started
        too many chats within the sliding window.

        Per user since 2026-09-26 (was global: the 6th person to click "New
        chat" in a minute was refused and lost their connection, L3-03).
        """
        uid = user_id or current_user_id()
        window_s = _config.NEW_CHATS_WINDOW_SECONDS
        per_user = _config.NEW_CHATS_PER_USER
        now = time.monotonic()
        cutoff = now - window_s
        mine = self._creation_timestamps.setdefault(uid, deque())
        self._prune(mine, cutoff)
        self._prune(self._global_creations, cutoff)
        # Drop empty per-user windows so the dict does not grow unbounded.
        for other in [k for k, v in self._creation_timestamps.items() if k != uid and not v]:
            self._creation_timestamps.pop(other, None)
        if per_user > 0 and len(mine) >= per_user:
            logger.warning(
                "New-chat rate limit for user %s: %d in last %ds (limit %d)",
                uid, len(mine), window_s, per_user,
            )
            raise SessionLimitError(
                NEW_CHAT_RATE_LIMIT_ERROR.format(limit=per_user, window=window_s),
                code="rate_limited",
            )
        global_limit = _config.NEW_CHATS_GLOBAL
        if global_limit > 0 and len(self._global_creations) >= global_limit:
            logger.warning(
                "Global new-chat rate limit: %d in last %ds (limit %d)",
                len(self._global_creations), window_s, global_limit,
            )
            raise SessionLimitError(GLOBAL_RATE_LIMIT_ERROR, code="rate_limited")

    def _record_creation(self, user_id: Optional[str] = None) -> None:
        """Record a chat creation for the rate limiter."""
        now = time.monotonic()
        self._creation_timestamps.setdefault(user_id or current_user_id(), deque()).append(now)
        self._global_creations.append(now)

    def touch(self, session_id: Optional[str]) -> None:
        """Mark a session as used now (LRU eviction order)."""
        if session_id:
            self._last_used[session_id] = time.monotonic()

    async def _evict_idle_sessions(self) -> int:
        """Evict idle sessions (not busy), least recently used first, until
        there is room for one more client.

        Returns the number of sessions evicted.
        """
        evicted = 0
        candidates = sorted(
            (sid for sid in list(self.sessions) if not self.is_session_busy(sid)),
            key=lambda sid: self._last_used.get(sid, 0.0),
        )
        for sid in candidates:
            if len(self.sessions) < MAX_SESSIONS:
                break  # We have room now
            logger.info("Evicting idle session %s to make room (at limit %d)", sid, MAX_SESSIONS)
            await self.cleanup_session_client(sid)
            evicted += 1
        return evicted

    async def _ensure_session_capacity(self) -> None:
        """Ensure there is room for one more live CLI client.

        First evicts idle sessions (LRU). If every live client is busy
        streaming, raises SessionLimitError.
        """
        if len(self.sessions) < MAX_SESSIONS:
            return  # Room available

        evicted = await self._evict_idle_sessions()
        if len(self.sessions) < MAX_SESSIONS:
            logger.info("Evicted %d idle session(s) to stay under limit %d", evicted, MAX_SESSIONS)
            return

        # All sessions are busy — cannot evict any
        logger.error(
            "Max concurrent sessions reached (%d) and all are busy. "
            "Rejecting new client.",
            MAX_SESSIONS,
        )
        raise SessionLimitError(CAPACITY_ERROR.format(limit=MAX_SESSIONS), code="capacity")

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
        # Role policy: a model the caller may not use falls back to the role's
        # default (e.g. an old chat created on Opus, resumed by a researcher).
        model = resolve_model(model or None)
        options = await build_agent_options(
            resume_session_id=resume_session_id,
            model_override=model or None,
        )
        client = await create_client_with_retry(
            options,
            max_retries=2,
            retry_delay=1.0,
            resume_session_id=resume_session_id,
        )
        tag_client(client, model=model or _config.MODEL, budget_usd=turn_budget_usd())
        return client

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
        self.touch(session_id)
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

        Used by ``ensure_session`` (case 2 — first message after opening a
        chat, after a cancel, or after the process was recycled) and by the
        CLI auto-recovery path. Honours the live-client cap: idle clients are
        evicted LRU-first, and SessionLimitError is raised if all are busy.
        """
        if session_id not in sessions_dict:
            await self._ensure_session_capacity()
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

        if claude_sid and self._is_client_alive(client) and getattr(client, "options", None) is not None \
                and getattr(client.options, "resume", None):
            # A resumed CLI restores the conversation's running cost total;
            # use the last recorded total as the per-question baseline.
            from synapsis.database.usage import last_cumulative_cost
            baseline = await last_cumulative_cost(session_id)
            try:
                client._ia_cost_baseline = float(baseline or 0.0)
            except Exception:
                pass

        sessions_dict[session_id] = client
        self.touch(session_id)
        return client

    async def replace_session_client(
        self,
        session_id: str,
        sessions_dict: dict,
        *,
        model: Optional[str],
        resume: bool = True,
    ) -> ClaudeSDKClient:
        """Tear down a chat's client and start a new one on ``model``.

        Used by ``switch_model`` and ``retry_with_model``: the old CLI process
        is always disconnected (the retry path used to orphan it, L3-06), the
        live-client cap is honoured, and the Claude conversation is resumed so
        the context is kept (``resume=False`` starts fresh).
        """
        if sessions_dict is self.sessions:
            await self.cleanup_session_client(session_id)
        else:  # pragma: no cover - callers always pass self.sessions
            old = sessions_dict.pop(session_id, None)
            if old is not None:
                try:
                    await old.disconnect()
                except Exception:
                    pass
        await self._ensure_session_capacity()
        claude_sid = await get_claude_session_id(session_id) if resume else ""
        client = await self._create_and_connect_client(
            resume_session_id=claude_sid or None, model=model,
        )
        if claude_sid:
            from synapsis.database.usage import last_cumulative_cost
            baseline = await last_cumulative_cost(session_id)
            try:
                client._ia_cost_baseline = float(baseline or 0.0)
            except Exception:
                pass
        sessions_dict[session_id] = client
        self.touch(session_id)
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
        self._last_used.pop(session_id, None)

    async def handle_new_session(
        self,
        sessions_dict: dict,
        send_json,
    ) -> tuple[str, Optional[ClaudeSDKClient]]:
        """Create a brand-new chat and return (session_id, None).

        Inserts the DB row and tells the frontend, but does NOT start a CLI
        subprocess: the client is created lazily by ``ensure_session`` when
        the first message is sent (so clicking "New chat" costs nothing and
        cannot exhaust the live-client cap).

        Raises SessionLimitError if this user's new-chat rate limit (or the
        deployment-wide safety net) is exceeded.
        """
        user_id = current_user_id()
        self._check_rate_limit(user_id)

        session_id = str(uuid.uuid4())[:SESSION_ID_LENGTH]
        await create_session(session_id)
        self._record_creation(user_id)
        await send_json({"type": "session", "session_id": session_id}, sid=session_id)
        return session_id, None

    async def handle_switch_session(
        self,
        payload: dict,
        sessions_dict: dict,
        send_json,
    ) -> Optional[tuple[str, Optional[ClaudeSDKClient]]]:
        """Switch the connection's active session.

        If the session's client is already in memory (and alive) it is reused.
        Otherwise NO client is started here (L3-04: browsing old chats used to
        spawn one CLI per click, bypassing the cap); the history is loaded by
        the frontend over REST and ``ensure_session`` resumes the Claude
        conversation when the user actually sends a message.

        Returns:
            (session_id, client_or_None) on success, or None if payload has no
            session_id.
        """
        requested_sid = payload.get("session_id", "")
        if not requested_sid:
            return None

        # Fast path: client already in memory — verify subprocess is alive
        if requested_sid in sessions_dict:
            client = sessions_dict[requested_sid]
            if self._is_client_alive(client):
                busy = self.is_session_busy(requested_sid)
                self.touch(requested_sid)
                await send_json(
                    {"type": "session", "session_id": requested_sid, "is_busy": busy},
                    sid=requested_sid,
                )
                return requested_sid, client
            # Subprocess died — discard; it is resumed lazily on the next message
            logger.warning(
                "Stale client detected on switch_session for %s — will resume on next message",
                requested_sid,
            )
            await self.cleanup_session_client(requested_sid)

        await send_json(
            {"type": "session", "session_id": requested_sid, "is_busy": False},
            sid=requested_sid,
        )
        return requested_sid, None

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
            recycle = getattr(client, "_ia_recycle", False) is True
            if not recycle and self._is_client_alive(client):
                self.touch(session_id)
                return session_id, client
            if recycle:
                # Budget headroom used up or the last answer stalled: replace
                # the CLI process (conversation resumed, cost counter reset).
                logger.info("Recycling CLI client for session %s before the next question", session_id)
                try:
                    await client.disconnect()
                except Exception:
                    pass
            else:
                # Subprocess died — discard the dead client and fall through to
                # Case 2, which looks up the claude_session_id and resumes.
                logger.warning(
                    "Stale client detected for session %s — subprocess exited, "
                    "discarding and recreating via resume",
                    session_id,
                )
            del sessions_dict[session_id]

        # Case 2: session exists but client was dropped (e.g. after a cancel,
        # a recycle, or a chat that was opened/created without a client yet)
        if session_id:
            client = await self._resume_or_create_client(session_id, sessions_dict)
            return session_id, client

        # Case 3: no session -- create one, using the first message as the title
        user_id = current_user_id()
        self._check_rate_limit(user_id)
        await self._ensure_session_capacity()

        session_id = str(uuid.uuid4())[:SESSION_ID_LENGTH]
        await create_session(session_id, title=user_message[:SESSION_TITLE_PREVIEW_LENGTH])
        client = await self._create_and_connect_client()
        sessions_dict[session_id] = client
        self._record_creation(user_id)
        self.touch(session_id)
        logger.info("New session %s", session_id)
        return session_id, client
