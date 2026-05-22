"""
Synapsis Analytics Agent - Provision Lambda
Assigns a user to an existing container or spins up a new one.
Bin-packs up to CONTAINERS_PER_INSTANCE containers per EC2 instance.

For cold starts (new EC2 instance), the handler returns 202 immediately
and invokes itself asynchronously to wait for SSM + start the container.
The frontend polls GET /status/{userId} until the container is healthy.
"""

import json
import os
import time
import random

import boto3

from lambda_utils import ec2, ssm, api_response, get_table

lam = boto3.client("lambda")

USERS_TABLE = get_table("USERS_TABLE")
INSTANCES_TABLE = get_table("INSTANCES_TABLE")
LAUNCH_TEMPLATE_ID = os.environ["LAUNCH_TEMPLATE_ID"]
LAUNCH_TEMPLATE_VERSION = os.environ["LAUNCH_TEMPLATE_VERSION"]
SUBNET_IDS = os.environ["SUBNET_IDS"].split(",")
ECR_IMAGE = os.environ["ECR_IMAGE"]
SECURITY_GROUP_ID = os.environ.get("SECURITY_GROUP_ID", "")
CONTAINERS_PER_INSTANCE = int(os.environ.get("CONTAINERS_PER_INSTANCE", "3"))
ENV_NAME = os.environ.get("ENVIRONMENT_NAME", "synapsis-agent")
FUNCTION_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "")

# Port allocation: container slot 0 -> 7701, slot 1 -> 7702, etc.
BASE_APP_PORT = 7701
# noVNC port allocation: container slot 0 -> 6081, slot 1 -> 6082, etc.
BASE_VNC_PORT = 6081


def handler(event, context):
    # --- Async callback: finish provisioning in the background ---
    if event.get("_async_provision"):
        return _async_finish(event["_async_provision"])

    # --- Synchronous path: called by API Gateway ---
    try:
        body = json.loads(event.get("body", "{}"))
    except (json.JSONDecodeError, TypeError):
        body = {}

    user_id = body.get("userId", "").strip()
    if not user_id:
        return api_response(400, {"error": "userId is required"})

    # Check if user already has a running container
    existing = USERS_TABLE.get_item(Key={"userId": user_id}).get("Item")
    if existing:
        return api_response(200, {
            "status": "ready",
            "appUrl": f"http://{existing['publicIp']}:{existing['appPort']}",
            "userId": user_id,
        })

    # Find an instance with available capacity
    instance = _find_available_instance()

    # Fast path: try bin-packing onto existing instances (with stale-record recovery)
    for _attempt in range(3):
        if not instance:
            break

        slot = int(instance["slotsUsed"])
        app_port = BASE_APP_PORT + slot
        vnc_port = BASE_VNC_PORT + slot
        instance_id = instance["instanceId"]
        public_ip = instance["publicIp"]

        try:
            _start_container(instance_id, user_id, app_port, vnc_port)
        except ssm.exceptions.InvalidInstanceId:
            # Instance is terminated — remove stale DynamoDB record and retry
            print(f"[provision] Stale instance {instance_id}, removing record")
            INSTANCES_TABLE.delete_item(Key={"instanceId": instance_id})
            instance = _find_available_instance()
            continue

        # Update DynamoDB
        INSTANCES_TABLE.update_item(
            Key={"instanceId": instance_id},
            UpdateExpression="SET slotsUsed = slotsUsed + :one",
            ExpressionAttributeValues={":one": 1},
        )
        USERS_TABLE.put_item(Item={
            "userId": user_id,
            "instanceId": instance_id,
            "containerName": f"synapsis-{user_id}",
            "appPort": app_port,
            "vncPort": vnc_port,
            "publicIp": public_ip,
            "launchedAt": int(time.time()),
            "lastActive": int(time.time()),
        })

        return api_response(200, {
            "status": "ready",
            "appUrl": f"http://{public_ip}:{app_port}",
            "vncUrl": f"http://{public_ip}:{vnc_port}/vnc.html",
            "userId": user_id,
            "coldStart": False,
        })

    # No capacity — launch a new EC2 instance (slow path)
    instance_id, public_ip = _launch_instance()
    slot = 0
    app_port = BASE_APP_PORT + slot
    vnc_port = BASE_VNC_PORT + slot

    # Register instance in DynamoDB
    INSTANCES_TABLE.put_item(Item={
        "instanceId": instance_id,
        "publicIp": public_ip,
        "slotsUsed": 0,
        "slotsTotal": CONTAINERS_PER_INSTANCE,
        "launchedAt": int(time.time()),
    })

    # Register user immediately (so status Lambda can find them)
    USERS_TABLE.put_item(Item={
        "userId": user_id,
        "instanceId": instance_id,
        "containerName": f"synapsis-{user_id}",
        "appPort": app_port,
        "vncPort": vnc_port,
        "publicIp": public_ip,
        "launchedAt": int(time.time()),
        "lastActive": int(time.time()),
    })

    # Fire-and-forget: invoke self asynchronously to wait for SSM + start container
    lam.invoke(
        FunctionName=FUNCTION_NAME,
        InvocationType="Event",  # async
        Payload=json.dumps({
            "_async_provision": {
                "instanceId": instance_id,
                "userId": user_id,
                "appPort": app_port,
                "vncPort": vnc_port,
            }
        }),
    )

    return api_response(202, {
        "status": "provisioning",
        "message": "Instance is starting. Poll GET /status/{userId} until ready.",
        "appUrl": f"http://{public_ip}:{app_port}",
        "vncUrl": f"http://{public_ip}:{vnc_port}/vnc.html",
        "userId": user_id,
        "coldStart": True,
    })


def _async_finish(params):
    """Background task: wait for SSM agent, then start the container."""
    instance_id = params["instanceId"]
    user_id = params["userId"]
    app_port = params["appPort"]
    vnc_port = params.get("vncPort", BASE_VNC_PORT)

    print(f"[async] Waiting for SSM on {instance_id} for user {user_id}...")

    if not _wait_for_ssm(instance_id, timeout=180):
        print(f"[async] SSM timeout for {instance_id} — user {user_id} may need to retry")
        return {"status": "ssm_timeout"}

    print(f"[async] SSM ready, starting container for {user_id}")
    try:
        _start_container(instance_id, user_id, app_port, vnc_port)
    except Exception as e:
        print(f"[async] Failed to start container for {user_id} on {instance_id}: {e}")
        return {"status": "container_start_failed"}

    INSTANCES_TABLE.update_item(
        Key={"instanceId": instance_id},
        UpdateExpression="SET slotsUsed = slotsUsed + :one",
        ExpressionAttributeValues={":one": 1},
    )
    print(f"[async] Container started for {user_id} on port {app_port}")
    return {"status": "done"}


def _find_available_instance():
    """Scan instances table for one with available slots."""
    result = INSTANCES_TABLE.scan(
        FilterExpression="slotsUsed < slotsTotal",
    )
    items = result.get("Items", [])
    if not items:
        return None

    # Prefer instances with most slots used (pack tightly)
    items.sort(key=lambda x: int(x["slotsUsed"]), reverse=True)
    return items[0]


def _launch_instance():
    """Launch a new EC2 instance from the launch template."""
    subnet = random.choice(SUBNET_IDS)

    response = ec2.run_instances(
        LaunchTemplate={
            "LaunchTemplateId": LAUNCH_TEMPLATE_ID,
            "Version": LAUNCH_TEMPLATE_VERSION,
        },
        # Subnet + security group via NetworkInterfaces override
        # (can't use SubnetId directly because launch template defines NetworkInterfaces)
        NetworkInterfaces=[{
            "DeviceIndex": 0,
            "SubnetId": subnet,
            "AssociatePublicIpAddress": True,
            "Groups": [SECURITY_GROUP_ID] if SECURITY_GROUP_ID else [],
        }],
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[{
            "ResourceType": "instance",
            "Tags": [
                {"Key": "Name", "Value": f"{ENV_NAME}-host"},
                {"Key": "ManagedBy", "Value": "synapsis-orchestrator"},
            ],
        }],
    )

    instance_id = response["Instances"][0]["InstanceId"]

    # Wait for the instance to be running
    ec2.get_waiter("instance_running").wait(InstanceIds=[instance_id])

    # Public IP assignment may lag behind instance_running state — poll until available
    public_ip = ""
    for _ in range(18):  # up to ~90s
        desc = ec2.describe_instances(InstanceIds=[instance_id])
        public_ip = desc["Reservations"][0]["Instances"][0].get("PublicIpAddress", "")
        if public_ip:
            break
        time.sleep(5)

    if not public_ip:
        print(f"[launch] WARNING: No public IP assigned to {instance_id} after 90s")

    return instance_id, public_ip


def _wait_for_ssm(instance_id, timeout=180):
    """Wait for SSM agent to be ready on the instance."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = ssm.describe_instance_information(
                Filters=[{"Key": "InstanceIds", "Values": [instance_id]}]
            )
            if response["InstanceInformationList"]:
                return True
        except Exception:
            pass
        time.sleep(5)
    return False


def _start_container(instance_id, user_id, app_port, vnc_port=None):
    """Start a Synapsis Agent container on the given instance via SSM."""
    if vnc_port is None:
        vnc_port = BASE_VNC_PORT
    container_name = f"synapsis-{user_id}"

    # Wait for Docker daemon and ECR image to be ready (UserData may still be running)
    wait_cmd = (
        f'for i in $(seq 1 60); do '
        f'  docker image inspect {ECR_IMAGE} >/dev/null 2>&1 && break; '
        f'  echo "[wait] Docker image not ready yet ($i/60)..."; '
        f'  sleep 5; '
        f'done'
    )

    run_cmd = (
        f"docker run -d --name {container_name} "
        f"--restart unless-stopped "
        f"-e ANTHROPIC_API_KEY=$(cat /root/.synapsis-api-key) "
        f"-e SYNAPSIS_MODEL=claude-opus-4-6 "
        f"-e SYNAPSIS_MAX_TURNS=100 "
        f"-e SYNAPSIS_PORT=7777 "
        f"-e SYNAPSIS_HOST=0.0.0.0 "
        f"--shm-size=512m "
        f"-v synapsis-workspace-{user_id}:/workspace "
        f"-p {app_port}:7777 "
        f"-p {vnc_port}:6080 "
        f"{ECR_IMAGE}"
    )

    ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [wait_cmd, run_cmd]},
        TimeoutSeconds=360,
    )


