"""Shared utilities for Synapsis Lambda functions."""

import json
import os

import boto3

# Shared AWS clients
ec2 = boto3.client("ec2")
ssm = boto3.client("ssm")
dynamodb = boto3.resource("dynamodb")


def get_table(env_var: str):
    """Get a DynamoDB table by environment variable name."""
    return dynamodb.Table(os.environ[env_var])


def api_response(status_code: int, body: dict) -> dict:
    """Standard API Gateway response with CORS headers."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body),
    }


def terminate_instance(instance_id: str, instances_table):
    """Terminate an EC2 instance and remove its DynamoDB record."""
    try:
        ec2.terminate_instances(InstanceIds=[instance_id])
        print(f"Terminated instance {instance_id}")
    except Exception as e:
        print(f"Warning: Failed to terminate {instance_id}: {e}")

    instances_table.delete_item(Key={"instanceId": instance_id})


def scan_all(table, **kwargs):
    """Paginated DynamoDB scan returning all items."""
    items = []
    response = table.scan(**kwargs)
    items.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"], **kwargs)
        items.extend(response.get("Items", []))
    return items
