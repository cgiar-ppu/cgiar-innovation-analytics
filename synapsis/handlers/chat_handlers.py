"""
WebSocket chat message handlers.

Each handler is responsible for one incoming message type that the WebSocket
dispatcher (websocket.py) may receive.  Handlers are pure async functions that
accept the minimal context they need and return updated per-connection state
where applicable.

Handler signatures follow the convention:
    async def handle_*(
        websocket_context: ...,   # send_json callable + per-connection state
        payload: dict,            # the parsed JSON frame from the client
        ...,                      # additional session / client refs as needed
    ) -> ...
"""

import time
from typing import Optional

from claude_agent_sdk import ClaudeSDKClient

import synapsis.config as _config
from synapsis.config import logger
from synapsis.constants import MODEL_NOT_ALLOWED_ERROR, SELECTABLE_MODEL_IDS
from synapsis.database import (
    save_message,
    consume_initial_context,
    update_session_model,
)
from synapsis.runtime_policy import (
    ModelNotAllowedError,
    PolicyError,
    current_role,
    current_user_id,
    enforce_daily_budget,
    fallback_model_for_role,
    is_model_allowed,
)
from synapsis.session import replace_session_client
from synapsis.chat_run_manager import chat_run_manager
from synapsis.scope import (
    ScopeValidationError,
    apply_scope_to_message,
    describe_scope,
    normalize_scope,
    scope_is_empty,
)
from synapsis.persona import (
    PersonaValidationError,
    apply_persona_to_message,
    describe_persona,
    normalize_persona,
    persona_is_empty,
)
from synapsis.session_manager import (
    sessions,
    handle_cancel as _sm_handle_cancel,
    handle_switch_session as _sm_handle_switch_session,
    handle_new_session as _sm_handle_handle_new_session,
    cancel_existing_task,
    ensure_session,
    get_session_lock,
    acquire_session_client,
    unregister_session_viewer,
    register_session_viewer,
    broadcast_to_session,
    broadcast_to_all,
    record_activity,
)
from synapsis.handlers.utils import launch_streaming_task


# ---------------------------------------------------------------------------
# handle_cancel
# ---------------------------------------------------------------------------

async def handle_cancel(
    payload: dict,
    session_id: Optional[str],
    client: Optional[ClaudeSDKClient],
    send_json,
) -> Optional[ClaudeSDKClient]:
    """Handle a ``{"type": "cancel"}`` frame.

    Supports targeted cancel: the client may pass ``session_id`` in the
    payload to cancel a specific (possibly background) session rather than
    always the currently active one.

    Returns the updated ``client`` reference for the active session -- None if
    the active session's client was torn down by the cancel.
    """
    from synapsis.database import update_session_task_status

    target_sid = payload.get("session_id", session_id) or session_id
    if target_sid != session_id and target_sid and not _config.AUTH_DISABLED:
        # L3-07: a targeted cancel may only stop the caller's own chats (the
        # same visibility rule as switch_session). Answer like "not found" so
        # session ids cannot be probed.
        from synapsis.auth.scoping import is_visible_to
        from synapsis.database import get_session_owner

        owner = await get_session_owner(target_sid)
        if not is_visible_to(owner, current_user_id(), current_role()):
            logger.warning(
                "Blocked cross-user cancel: user %s -> session %s (owner %s)",
                current_user_id(), target_sid, owner,
            )
            await send_json({"type": "error", "message": "Session not found."}, sid=target_sid)
            return client
    # Prefer the live client in the registry: after a lazy switch_session the
    # connection's local ``client`` may still be None while an answer streams.
    target_client = sessions.get(target_sid) or (client if target_sid == session_id else None)

    # Cancel the managed streaming task via ChatRunManager
    await chat_run_manager.cancel(target_sid)

    # Tear down the SDK client (abort, disconnect, remove from sessions dict)
    await _sm_handle_cancel(
        target_sid, target_client, sessions, send_json
    )

    # Broadcast the cancelled event to all OTHER devices viewing this session
    # so they are notified (the cancelling device already received it from
    # _sm_handle_cancel above).
    if target_sid:
        await broadcast_to_session(
            target_sid,
            {"type": "cancelled", "session_id": target_sid},
            exclude=send_json,
        )

    # Update task status to idle
    if target_sid:
        await update_session_task_status(target_sid, "idle")

    # If the active session's client was disconnected, clear the local ref
    if target_sid == session_id and session_id and session_id not in sessions:
        return None
    return client


# ---------------------------------------------------------------------------
# handle_switch_session
# ---------------------------------------------------------------------------

async def handle_switch_session(
    payload: dict,
    session_id: Optional[str],
    send_json,
) -> tuple[Optional[str], Optional[ClaudeSDKClient], bool]:
    """Handle a ``{"type": "switch_session", "session_id": "..."}`` frame.

    Delegates to session_manager and updates the connection's viewer registry.
    Also checks whether the target session has an active streaming task that
    the caller should attach to.

    Returns:
        (new_session_id, new_client, needs_attach) -- needs_attach is True if
        the session has a running managed task that the WebSocket should
        subscribe to via ChatRunManager.
    """
    old_sid = session_id

    result = await _sm_handle_switch_session(payload, sessions, send_json)
    if result:
        new_session_id, new_client = result
        if old_sid:
            unregister_session_viewer(old_sid, send_json)
        register_session_viewer(new_session_id, send_json)
        needs_attach = chat_run_manager.is_running(new_session_id)
        return new_session_id, new_client, needs_attach

    return session_id, None, False


# ---------------------------------------------------------------------------
# handle_new_session
# ---------------------------------------------------------------------------

async def handle_new_session(
    session_id: Optional[str],
    send_json,
) -> tuple[str, Optional[ClaudeSDKClient]]:
    """Handle a ``{"type": "new_session"}`` frame.

    Delegates to session_manager (which enforces the per-user new-chat rate
    limit and creates only the DB row -- the CLI starts on the first message)
    and moves this connection's viewer registration to the new chat. On a
    rate-limit error nothing changes and the error propagates.

    Returns:
        (new_session_id, None)
    """
    new_session_id, new_client = await _sm_handle_handle_new_session(sessions, send_json)
    if session_id:
        unregister_session_viewer(session_id, send_json)
    register_session_viewer(new_session_id, send_json)
    return new_session_id, new_client


# ---------------------------------------------------------------------------
# handle_retry
# ---------------------------------------------------------------------------

async def handle_retry(
    payload: dict,
    session_id: Optional[str],
    send_json,
) -> Optional[ClaudeSDKClient]:
    """Handle a ``{"type": "retry_with_model"}`` frame.

    Creates a fresh SDK client with the requested (or fallback) model,
    replaces the in-memory session client, acquires the per-session lock,
    and launches a managed streaming task via the ChatRunManager.

    Honours the same optional ``"scope"`` object and ``"agent"`` selection as a
    regular user message, so a retry after an AUP fallback stays inside the
    user's active filters AND keeps their chosen specialist.

    Returns the newly created ``retry_client``, or None if the payload
    carries no message text / carries an invalid scope or agent id (in which
    case nothing is done).
    """
    retry_message = payload.get("message", "").strip()
    retry_model = payload.get("model", "")
    if not retry_message:
        return None

    try:
        scope = normalize_scope(payload.get("scope"))
    except ScopeValidationError as exc:
        await send_json(
            {"type": "error", "message": f"Invalid data scope: {exc}"},
            sid=session_id,
        )
        return None

    try:
        persona = normalize_persona(payload.get("agent"))
    except PersonaValidationError as exc:
        await send_json(
            {"type": "error", "message": f"Invalid agent selection: {exc}"},
            sid=session_id,
        )
        return None

    # L3-06: validate against the caller's allowed models (like switch_model)
    # BEFORE doing anything. No explicit model = the role's fallback model,
    # and a role without one (researchers by default) cannot retry on another
    # model.
    model_to_use = (retry_model or "").strip() or fallback_model_for_role()
    if (
        not model_to_use
        or model_to_use not in SELECTABLE_MODEL_IDS
        or not is_model_allowed(model_to_use)
    ):
        raise ModelNotAllowedError(MODEL_NOT_ALLOWED_ERROR.format(model=model_to_use or retry_model or "?"))
    if not session_id:
        await send_json({"type": "error", "message": "No active chat to retry in."})
        return None

    await enforce_daily_budget()

    # Cancel any in-flight managed task for this session
    await chat_run_manager.cancel(session_id)

    # Disconnect the old CLI (was orphaned) and resume the conversation on the
    # retry model so the context is kept (was silently dropped).
    await update_session_model(session_id, model_to_use)
    retry_client = await replace_session_client(session_id, sessions, model=model_to_use, resume=True)

    retry_lock_acquired = False
    if session_id:
        retry_lock = get_session_lock(session_id)
        await retry_lock.acquire()
        retry_lock_acquired = True

    # Persist the user's text unmodified; only the SDK copy carries the scope.
    await save_message(session_id, "user", {"content": retry_message})

    await launch_streaming_task(
        session_id, retry_client,
        apply_persona_to_message(
            apply_scope_to_message(retry_message, scope), persona
        ),
        send_json,
        lock_acquired=retry_lock_acquired,
    )

    return retry_client


# ---------------------------------------------------------------------------
# handle_switch_model
# ---------------------------------------------------------------------------

async def handle_switch_model(
    payload: dict,
    session_id: Optional[str],
    send_json,
) -> Optional[ClaudeSDKClient]:
    """Handle a ``{"type": "switch_model", "model": "..."}`` frame.

    Switches the active session to a different model mid-conversation:
    1. Validates the requested model against SELECTABLE_MODEL_IDS.
    2. Cancels any in-flight managed task for the session.
    3. Persists the new model to the sessions table FIRST, so any resume path
       (reconnect, REST send) picks up the new model.
    4. Tears down the old SDK client subprocess.
    5. Creates a fresh client with ``model_override`` and resumes the Claude
       SDK session (preserving conversation context).
    6. Broadcasts ``model_switched`` to all viewers of the session.

    Returns the new client on success, or None on validation failure / connect
    error (in which case the caller keeps its existing client ref).
    """
    new_model = payload.get("model", "").strip()
    # Must be a curated model, exposed by this deployment AND allowed for the
    # caller's role (non-admins: the researcher list, Sonnet 5 by default).
    if new_model not in SELECTABLE_MODEL_IDS or not is_model_allowed(new_model):
        raise ModelNotAllowedError(MODEL_NOT_ALLOWED_ERROR.format(model=new_model))
    if not session_id:
        await send_json(
            {"type": "error", "message": "No active session to switch model on"}
        )
        return None

    logger.info("Switching session %s to model %s", session_id, new_model)

    # Cancel any in-flight managed task for this session
    await chat_run_manager.cancel(session_id)

    # Persist first so any resume path picks up the new model
    await update_session_model(session_id, new_model)

    # Tear down the old subprocess and resume the conversation under the new
    # model (honours the live-client cap).
    try:
        new_client = await replace_session_client(session_id, sessions, model=new_model, resume=True)
    except PolicyError:
        raise
    except Exception:
        logger.exception("Model switch failed for session %s", session_id)
        await send_json(
            {"type": "error", "message": "Switching the model failed. Please try again."},
            sid=session_id,
        )
        return None

    # Confirm to the switching device and all other viewers
    confirm = {"type": "model_switched", "model": new_model, "session_id": session_id}
    await send_json(confirm, sid=session_id)
    await broadcast_to_session(session_id, confirm, exclude=send_json)
    await broadcast_to_all({"type": "sessions_changed"}, exclude=send_json)

    return new_client


# ---------------------------------------------------------------------------
# handle_user_message
# ---------------------------------------------------------------------------

async def handle_user_message(
    payload: dict,
    session_id: Optional[str],
    send_json,
) -> tuple[str, ClaudeSDKClient]:
    """Handle a regular ``{"message": "..."}`` user chat frame.

    Records activity, cancels any existing in-flight task, guarantees a valid
    session and connected SDK client via ``ensure_session``, persists the user
    message, acquires the per-session lock, sends the message to the agent, and
    launches a managed streaming task via the ChatRunManager.

    The frame may carry an optional ``"scope"`` object
    (``{"years": [...], "programs": [...]}``) set by the UI filter bar, and an
    optional ``"agent"`` string (a builtin specialist id) set by the agent
    picker. Both are validated here and rendered into delimited preambles that
    are prepended to the copy of the message handed to the SDK — see
    synapsis/scope.py and synapsis/persona.py for why the injection is
    per-message rather than in the shared system-prompt file. The persisted
    user message is never modified.

    Returns:
        (session_id, client) -- the (possibly newly created) session and client.

    Raises:
        ValueError: If the payload carries an empty message string, or an
                    invalid scope (caller should skip the frame; an error frame
                    has already been sent to the client in the scope case).
    """
    user_message = payload.get("message", "").strip()
    if not user_message:
        raise ValueError("Empty user message -- frame should be skipped")

    # Validate the optional active-data-scope BEFORE doing any work, so a
    # malformed filter payload can never reach the agent half-applied.
    try:
        scope = normalize_scope(payload.get("scope"))
    except ScopeValidationError as exc:
        await send_json(
            {"type": "error", "message": f"Invalid data scope: {exc}"},
            sid=session_id,
        )
        raise ValueError(f"Invalid scope: {exc}") from None

    # Same discipline for the optional selected specialist (F3): validate the
    # id before any work happens, so a bad picker payload can never reach the
    # agent half-applied.
    try:
        persona = normalize_persona(payload.get("agent"))
    except PersonaValidationError as exc:
        await send_json(
            {"type": "error", "message": f"Invalid agent selection: {exc}"},
            sid=session_id,
        )
        raise ValueError(f"Invalid agent: {exc}") from None

    # Soft daily spend cap per user (admins exempt): refuse politely before
    # any work is done. Raises DailyBudgetExceeded -> error frame.
    await enforce_daily_budget()

    await record_activity(time.time())

    # Cancel any existing in-flight managed task before starting a new one
    await cancel_existing_task(session_id)

    # Guarantee a valid session and connected SDK client
    session_id, client = await ensure_session(session_id, user_message, sessions)

    # Notify the frontend which session is active for this response
    await send_json({"type": "session", "session_id": session_id}, sid=session_id)

    # Persist the user's message to the database
    await save_message(session_id, "user", {"content": user_message})

    # Check if this session has initial context (e.g. from workflow continuation)
    # that needs to be prepended to the first message sent to the SDK.
    initial_context = await consume_initial_context(session_id)
    if initial_context:
        sdk_message = (
            f"<workflow_context>\n{initial_context}\n</workflow_context>\n\n"
            f"{user_message}"
        )
        logger.info(
            "Prepending workflow context to first message for session %s", session_id
        )
    else:
        sdk_message = user_message

    # Prepend the active data scope (year / programme filters) so the agent
    # constrains its PRMS queries AND states the slice in its answer. No-op
    # when the user has set no filters.
    if not scope_is_empty(scope):
        sdk_message = apply_scope_to_message(sdk_message, scope)
        logger.info(
            "Applying active data scope to session %s: %s",
            session_id, describe_scope(scope),
        )

    # Prepend the selected specialist LAST so its block sits at the very top of
    # the message the orchestrator reads. No-op when nothing is picked, which
    # keeps the default routing byte-identical to the pre-picker behaviour.
    if not persona_is_empty(persona):
        sdk_message = apply_persona_to_message(sdk_message, persona)
        logger.info(
            "Routing session %s to selected specialist: %s",
            session_id, describe_persona(persona),
        )

    # Acquire the per-session lock before querying
    client, lock_acquired = await acquire_session_client(session_id, sessions)

    await launch_streaming_task(
        session_id, client, sdk_message, send_json,
        lock_acquired=lock_acquired,
    )

    # Notify other devices that this session was updated
    await broadcast_to_all(
        {"type": "sessions_changed"},
        exclude=send_json,
    )
    # Notify other devices viewing this session that streaming started
    await broadcast_to_session(
        session_id,
        {"type": "session_streaming_started", "session_id": session_id},
        exclude=send_json,
    )

    return session_id, client
