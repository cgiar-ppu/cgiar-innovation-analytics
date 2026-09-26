"""
WebSocket surface gate (review 2026-09-23, P0-1 / L7-01 / L7-02).

The Synapsis fork shipped three extra sockets -- ``/ws/agent/{id}``,
``/ws/workflow/{id}`` and ``/ws/fleet/{id}`` -- that accepted anonymous
handshakes and drove a shell-capable agent. FastAPI never lists WebSocket
routes in ``openapi.json``, so the release smoke's anonymous sweep could not
see them. These tests enumerate ``app.routes`` directly:

* the ONLY WebSocket route is ``/ws/chat``;
* every WebSocket route rejects an anonymous handshake when auth is enforced
  (close 1008 before ``accept``);
* the removed paths no longer upgrade at all.

No model, no network, no database: the handshake is rejected before the
handler touches anything.
"""

from unittest.mock import patch

import pytest
from starlette.routing import WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from fastapi.routing import APIWebSocketRoute

#: The complete, intended WebSocket surface of the IA app.
EXPECTED_WS_PATHS = {"/ws/chat"}

#: Synapsis-era sockets that must never come back.
REMOVED_WS_PATHS = ["/ws/agent/orchestrator", "/ws/workflow/x", "/ws/fleet/x"]


def _ws_paths(app) -> set[str]:
    return {
        r.path
        for r in app.routes
        if isinstance(r, (WebSocketRoute, APIWebSocketRoute))
    }


def test_only_the_chat_websocket_is_registered():
    from synapsis.server import app

    assert _ws_paths(app) == EXPECTED_WS_PATHS


@pytest.mark.parametrize("path", sorted(EXPECTED_WS_PATHS))
def test_every_websocket_rejects_an_anonymous_handshake(path):
    from synapsis.server import app

    with (
        patch("synapsis.config.AUTH_DISABLED", False),
        patch("synapsis.websocket.AUTH_DISABLED", False),
    ):
        client = TestClient(app)
        # No token at all.
        with pytest.raises(WebSocketDisconnect) as no_token:
            with client.websocket_connect(path) as ws:
                ws.receive_json()
        assert no_token.value.code == 1008
        # A forged/garbage token.
        with pytest.raises(WebSocketDisconnect) as bad_token:
            with client.websocket_connect(f"{path}?token=not-a-jwt") as ws:
                ws.receive_json()
        assert bad_token.value.code == 1008


@pytest.mark.parametrize("path", REMOVED_WS_PATHS)
def test_removed_synapsis_sockets_do_not_upgrade(path):
    from synapsis.server import app

    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(path) as ws:
            ws.receive_json()


def test_removed_socket_modules_are_gone():
    import importlib

    for mod in ("synapsis.agent_ws", "synapsis.workflow_ws", "synapsis.fleet_ws"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(mod)
