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

from synapsis.config import logger, FALLBACK_MODEL, AVAILABLE_MODELS
from synapsis.constants import SELECTABLE_MODEL_IDS
from synapsis.agent_options import build_agent_options
from synapsis.database import (
    save_message,
    consume_initial_context,
    get_claude_session_id,
    update_session_model,
)
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

    target_sid = payload.get("session_id", session_id)
    target_client = sessions.get(target_sid) if target_sid != session_id else client

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
) -> tuple[str, ClaudeSDKClient]:
    """Handle a ``{"type": "new_session"}`` frame.

    Optionally unregisters the current session viewer, delegates to
    session_manager, and registers the new session viewer.

    Returns:
        (new_session_id, new_client)
    """
    if session_id:
        unregister_session_viewer(session_id, send_json)

    new_session_id, new_client = await _sm_handle_handle_new_session(sessions, send_json)
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

    # Cancel any in-flight managed task for this session
    await chat_run_manager.cancel(session_id)

    model_to_use = retry_model or FALLBACK_MODEL
    options = await build_agent_options(resume_session_id=None, model_override=model_to_use)
    retry_client = ClaudeSDKClient(options=options)
    await retry_client.connect()

    # Replace the tracked client for this session
    if session_id:
        sessions[session_id] = retry_client

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
    from synapsis.session_manager import cleanup_session_client

    new_model = payload.get("model", "").strip()
    # Must be a curated model AND allowed by this deployment's
    # SYNAPSIS_AVAILABLE_MODELS allow-list (defaults to all curated models).
    if new_model not in SELECTABLE_MODEL_IDS or new_model not in AVAILABLE_MODELS:
        await send_json(
            {"type": "error", "message": f"Invalid model '{new_model}'"},
            sid=session_id,
        )
        return None
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

    # Tear down the old subprocess
    await cleanup_session_client(session_id)

    # Resume the Claude SDK conversation (if any) under the new model
    claude_sid = await get_claude_session_id(session_id)
    try:
        options = await build_agent_options(
            resume_session_id=claude_sid or None, model_override=new_model
        )
        new_client = ClaudeSDKClient(options=options)
        await new_client.connect()
    except Exception as exc:
        logger.exception("Model switch failed for session %s", session_id)
        await send_json(
            {"type": "error", "message": f"Model switch failed: {exc}"},
            sid=session_id,
        )
        return None

    sessions[session_id] = new_client

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
