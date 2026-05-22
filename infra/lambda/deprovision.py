"""
Synapsis Analytics Agent - Deprovision Lambda
Stops and removes a user's container.
Terminates the EC2 instance if it has no remaining containers.
"""

from lambda_utils import ssm, dynamodb, api_response, terminate_instance, get_table

USERS_TABLE = get_table("USERS_TABLE")
INSTANCES_TABLE = get_table("INSTANCES_TABLE")


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
        })

    instance_id = item["instanceId"]
    container_name = item.get("containerName", f"synapsis-{user_id}")

    # Stop and remove the container via SSM
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
        print(f"Warning: SSM command failed for {instance_id}: {e}")

    # Remove user entry
    USERS_TABLE.delete_item(Key={"userId": user_id})

    # Decrement slots on instance
    try:
        INSTANCES_TABLE.update_item(
            Key={"instanceId": instance_id},
            UpdateExpression="SET slotsUsed = slotsUsed - :one",
            ExpressionAttributeValues={":one": 1},
            ConditionExpression="slotsUsed > :zero",
            ExpressionAttributeNames={},
        )
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        pass

    # Check if instance is now empty
    inst = INSTANCES_TABLE.get_item(Key={"instanceId": instance_id}).get("Item")
    if inst and int(inst.get("slotsUsed", 0)) <= 0:
        # Terminate empty instance
        terminate_instance(instance_id, INSTANCES_TABLE)

    return api_response(200, {
        "status": "deprovisioned",
        "userId": user_id,
    })


