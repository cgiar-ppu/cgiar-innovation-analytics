"""
Cancellation -- in-flight task and SDK client teardown for cancel requests.

Provides ``cancel_existing_task`` (delegates to ChatRunManager) and
``handle_cancel`` (aborts the SDK client and cleans up session state).
"""

from typing import Optional

from claude_agent_sdk import ClaudeSDKClient

from synapsis.config import logger
from synapsis.session.client_registry import ClientRegistry


class CancelManager:
    """Handles cancellation of in-flight tasks and SDK client teardown."""

    def __init__(self, client_registry: ClientRegistry) -> None:
        self._clients = client_registry

    async def cancel_existing_task(self, session_id: Optional[str]) -> None:
        """Cancel any in-flight managed chat task for the given session.

        Delegates to the ChatRunManager which owns task lifecycle.
        """
        if not session_id:
            return
        from synapsis.chat_run_manager import chat_run_manager
        await chat_run_manager.cancel(session_id)

    async def handle_cancel(
        self,
        session_id: Optional[str],
        client: Optional[ClaudeSDKClient],
        sessions_dict: dict,
        send_json,
    ) -> None:
        """Handle SDK client teardown for a cancel request.

        Aborts the SDK client, removes it from the sessions dict (so
        ensure_session() will reconnect fresh on the next message), releases
        the per-session lock, and sends a "cancelled" acknowledgement.

        Task cancellation is handled separately by the caller via
        ``chat_run_manager.cancel()``.
        """
        logger.info("Cancel requested (session %s)", session_id)

        # Abort and disconnect the SDK client. We must fully tear down the
        # client to avoid stale buffered response data leaking into the next
        # query. The client is removed from sessions_dict so ensure_session()
        # will reconnect fresh (with resume_session_id) on the next message.
        if client:
            try:
                if hasattr(client, "abort"):
                    await client.abort()
                elif hasattr(client, "interrupt"):
                    await client.interrupt()
            except Exception:
                # SDK abort/interrupt may raise anything; ignore on cancel teardown
                pass
            try:
                await client.disconnect()
            except Exception:
                # SDK disconnect may raise anything; ignore on cancel teardown
                pass
            sessions_dict.pop(session_id, None)

        # Release the per-session lock so the next connection can acquire it.
        if session_id:
            self._clients.release_session_client(session_id)

        await send_json({"type": "cancelled"}, sid=session_id)
