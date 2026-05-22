"""
Synapsis Analytics Agent - Cleanup Lambda (EventBridge cron, every 5 minutes)
Stops idle containers and terminates empty instances.

Activity detection: Before killing a container, we check the container's
/api/activity endpoint which reports active WebSocket connections and last
user interaction time. This prevents killing containers that are actively
in use — the DynamoDB lastActive field alone is insufficient because only
the status Lambda updates it, and nothing calls the status Lambda once the
user opens the app.
"""

import json
import os
import time
import urllib.request
import urllib.error

from lambda_utils import ec2, ssm, terminate_instance, scan_all, get_table

USERS_TABLE = get_table("USERS_TABLE")
INSTANCES_TABLE = get_table("INSTANCES_TABLE")
IDLE_TIMEOUT = int(os.environ.get("IDLE_TIMEOUT_MINUTES", "30")) * 60  # seconds
MAX_LIFETIME = int(os.environ.get("MAX_INSTANCE_LIFETIME_MINUTES", "480")) * 60  # seconds


def handler(event, context):
    now = int(time.time())
    cleaned_users = 0
    terminated_instances = 0

    # 1. Find and remove idle user containers
    users = scan_all(USERS_TABLE)
    for user in users:
        last_active = int(user.get("lastActive", 0))
        if (now - last_active) > IDLE_TIMEOUT:
            # Before killing, check if the container is actually in use
            if _container_is_active(user, now):
                print(f"Container still active for {user['userId']}, refreshing lastActive")
                USERS_TABLE.update_item(
                    Key={"userId": user["userId"]},
                    UpdateExpression="SET lastActive = :now",
                    ExpressionAttributeValues={":now": now},
                )
                continue
            print(f"Idle user: {user['userId']} (last active {now - last_active}s ago)")
            _stop_container(user)
            cleaned_users += 1

    # 2. Find and terminate empty instances OR instances past max lifetime
    instances = scan_all(INSTANCES_TABLE)
    for inst in instances:
        slots_used = int(inst.get("slotsUsed", 0))
        instance_id = inst["instanceId"]
        launched_at = int(inst.get("launchedAt", 0))
        instance_age = now - launched_at

        # Hard max lifetime — last-resort safety net
        if instance_age > MAX_LIFETIME:
            print(f"Max lifetime exceeded: {instance_id} (age={instance_age}s)")
            _cleanup_users_on_instance(instance_id, users)
            terminate_instance(instance_id, INSTANCES_TABLE)
            terminated_instances += 1
        elif slots_used <= 0:
            # Give newly launched instances a grace period (10 min)
            if instance_age > 600:
                print(f"Terminating empty instance: {instance_id}")
                terminate_instance(instance_id, INSTANCES_TABLE)
                terminated_instances += 1
        else:
            # Verify the EC2 instance is still running
            if not _instance_exists(instance_id):
                print(f"Instance {instance_id} no longer exists, cleaning up DynamoDB")
                _cleanup_orphaned_instance(instance_id)

    result = {
        "cleaned_users": cleaned_users,
        "terminated_instances": terminated_instances,
        "total_users_scanned": len(users),
        "total_instances_scanned": len(instances),
    }
    print(f"Cleanup result: {json.dumps(result)}")
    return result


def _container_is_active(user, now):
    """Check the container's /api/activity endpoint to see if it's actually in use.
    Returns True if there are active WebSocket connections or recent user interaction."""
    public_ip = user.get("publicIp", "")
    app_port = int(user.get("appPort", 0))
    if not public_ip or not app_port:
        return False
    try:
        url = f"http://{public_ip}:{app_port}/api/activity"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        # Active if anyone is connected via WebSocket
        if data.get("active_connections", 0) > 0:
            return True
        # Active if any activity (user message or agent streaming) within the timeout
        last_activity = data.get("last_activity", 0)
        if last_activity and (now - last_activity) < IDLE_TIMEOUT:
            return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError):
        # Container unreachable — not active
        pass
    return False


def _stop_container(user):
    """Stop a user's container and clean up DynamoDB."""
    instance_id = user["instanceId"]
    container_name = user.get("containerName", f"synapsis-{user['userId']}")

    try:
        ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={
                "commands": [f"docker stop {container_name} && docker rm {container_name}"]
            },
            TimeoutSeconds=30,
        )
    except Exception as e:
        print(f"Warning: Could not stop container on {instance_id}: {e}")

    # Remove user entry
    USERS_TABLE.delete_item(Key={"userId": user["userId"]})

    # Decrement slots
    try:
        INSTANCES_TABLE.update_item(
            Key={"instanceId": instance_id},
            UpdateExpression="SET slotsUsed = slotsUsed - :one",
            ExpressionAttributeValues={":one": 1},
            ConditionExpression="slotsUsed > :zero",
        )
    except Exception:
        pass


def _instance_exists(instance_id):
    """Check if an EC2 instance is still running."""
    try:
        response = ec2.describe_instance_status(
            InstanceIds=[instance_id],
            IncludeAllInstances=True,
        )
        statuses = response.get("InstanceStatuses", [])
        if not statuses:
            return False
        state = statuses[0]["InstanceState"]["Name"]
        return state in ("pending", "running")
    except Exception:
        return False


def _cleanup_orphaned_instance(instance_id):
    """Remove DynamoDB entries for an instance that no longer exists."""
    # Find all users on this instance
    users = scan_all(USERS_TABLE)
    for user in users:
        if user.get("instanceId") == instance_id:
            USERS_TABLE.delete_item(Key={"userId": user["userId"]})

    INSTANCES_TABLE.delete_item(Key={"instanceId": instance_id})


def _cleanup_users_on_instance(instance_id, users):
    """Stop containers and remove DynamoDB entries for all users on an instance."""
    for user in users:
        if user.get("instanceId") == instance_id:
            _stop_container(user)


