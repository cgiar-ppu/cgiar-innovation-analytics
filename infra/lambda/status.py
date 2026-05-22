"""
Synapsis Analytics Agent - Status Lambda
Checks if a user's container is running and healthy.
Updates lastActive timestamp on successful health checks.
"""

import time
import urllib.request
import urllib.error

from lambda_utils import api_response, get_table

USERS_TABLE = get_table("USERS_TABLE")


def handler(event, context):
    user_id = event.get("pathParameters", {}).get("userId", "")
    if not user_id:
        return api_response(400, {"error": "userId is required"})

    # Look up user's container
    item = USERS_TABLE.get_item(Key={"userId": user_id}).get("Item")
    if not item:
        return api_response(404, {
            "status": "not_found",
            "message": "No container provisioned for this user",
            "userId": user_id,
        })

    public_ip = item["publicIp"]
    app_port = int(item["appPort"])

    # Health check
    healthy = _check_health(public_ip, app_port)

    if healthy:
        # Update lastActive
        USERS_TABLE.update_item(
            Key={"userId": user_id},
            UpdateExpression="SET lastActive = :now",
            ExpressionAttributeValues={":now": int(time.time())},
        )

    return api_response(200, {
        "status": "ready" if healthy else "starting",
        "healthy": healthy,
        "appUrl": f"http://{public_ip}:{app_port}",
        "userId": user_id,
        "launchedAt": int(item.get("launchedAt", 0)),
        "lastActive": int(item.get("lastActive", 0)),
    })


def _check_health(ip, port, timeout=5):
    """Call the FastAPI health endpoint."""
    url = f"http://{ip}:{port}/api/health"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False
