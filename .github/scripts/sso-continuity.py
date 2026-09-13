"""DEV-only, read-only database comparison around the normal container update.

Executed by the authorized Actions role. Never outputs users, titles, messages,
passwords or credentials: only hashed ownership rows and aggregate counts.
"""
import base64
import json
import os
from pathlib import Path
import shlex
import sys
import time

import boto3

region = "eu-central-1"
assert boto3.client("sts", region_name=region).get_caller_identity()["Account"] == "972793825893"
instance = os.environ["IA_INSTANCE_ID"]
ssm = boto3.client("ssm", region_name=region)
code = '''
import hashlib, json, sqlite3
db = sqlite3.connect('file:/workspace/.synapsis/chat.db?mode=ro', uri=True)
def hashes(query):
    return sorted(hashlib.sha256(json.dumps(list(row)).encode()).hexdigest() for row in db.execute(query))
print(json.dumps({'ownership': hashes('SELECT session_id, user_id FROM sessions'),
 'users': hashes('SELECT email, name, role FROM users'),
 'messages': db.execute('SELECT COUNT(*) FROM messages').fetchone()[0]}))
'''
encoded = base64.b64encode(code.encode()).decode()
command = "docker exec cgiar-innovation-analytics python -c " + shlex.quote(
    "import base64;exec(base64.b64decode(" + repr(encoded) + "))")
command_id = ssm.send_command(
    InstanceIds=[instance], DocumentName="AWS-RunShellScript",
    Parameters={"commands": [command]}, TimeoutSeconds=60,
)['Command']['CommandId']
for _ in range(40):
    try:
        result = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance)
    except ssm.exceptions.InvocationDoesNotExist:
        time.sleep(2)
        continue
    if result["Status"] == "Success":
        snapshot = json.loads(result["StandardOutputContent"])
        break
    if result["Status"] in {"Failed", "TimedOut", "Cancelled"}:
        raise RuntimeError("DEV continuity inspection failed; inspect SSM command " + command_id)
    time.sleep(2)
else:
    raise TimeoutError("DEV continuity inspection timed out")
path = Path("sso-continuity-before.json")
if sys.argv[1] == "before":
    path.write_text(json.dumps(snapshot))
else:
    before = json.loads(path.read_text())
    assert set(before["ownership"]).issubset(snapshot["ownership"]), "Existing chat ownership changed or sessions disappeared"
    assert set(before["users"]).issubset(snapshot["users"]), "Existing application users or roles changed"
    assert snapshot["messages"] >= before["messages"], "Message count decreased"
    print("Verified all existing sessions, ownership, users and roles preserved.")
print(json.dumps({"phase": sys.argv[1], "sessions": len(snapshot["ownership"]),
                  "users": len(snapshot["users"]), "messages": snapshot["messages"]}))
