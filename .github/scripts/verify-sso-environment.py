"""Fail closed before deploying an app with another environment's identity.

Read-only checks. Values are non-secret GitHub deployment-environment variables.
"""
import json
import os
import re
import subprocess
from urllib.parse import urlparse


def aws(*args):
    return json.loads(subprocess.check_output(["aws", *args, "--output", "json"], text=True))


region = os.environ["AWS_REGION"]
account = os.environ["EXPECTED_ACCOUNT"].strip()
issuer = os.environ["SSO_ISSUER"]
client_id = os.environ["SSO_CLIENT"]
domain = os.environ["SSO_DOMAIN"]
origin = os.environ["SSO_ORIGIN"]
admins = os.environ["SSO_ADMINS"]
invited = os.environ["INVITED_ENABLED"]
match = re.fullmatch(r"https://cognito-idp\.([a-z0-9-]+)\.amazonaws\.com/([A-Za-z0-9_-]+)", issuer)
assert match and match[1] == region, "Set this environment's IA_SSO_ISSUER before deploying"
pool = match[2]
assert re.fullmatch(r"[a-z0-9]+", client_id), "Missing/invalid environment Cognito client"
for value in (domain, origin):
    assert re.fullmatch(r"https://[A-Za-z0-9.-]+", value), "SSO domain/origin must be explicit HTTPS origins without trailing slashes"
assert not admins or re.fullmatch(r"[a-f0-9-]+(?:,[a-f0-9-]+)*", admins), "Invalid configured administrator subjects"
assert invited in ("true", "false"), "Invalid invited-login flag"
assert invited != "true" or admins, "Invitations require a configured CGIAR administrator"
pool_arn = aws("cognito-idp", "describe-user-pool", "--user-pool-id", pool,
               "--query", "UserPool.Arn")
assert pool_arn.split(":")[4] == account, "Cognito pool is in another AWS account"
client = aws("cognito-idp", "describe-user-pool-client", "--user-pool-id", pool,
             "--client-id", client_id, "--query",
             "UserPoolClient.{callbacks:CallbackURLs,logouts:LogoutURLs,providers:SupportedIdentityProviders}")
assert origin + "/auth/callback" in client["callbacks"], "App callback is not registered on this environment's client"
assert origin in client["logouts"], "Logout origin is not registered"
assert "AzureAD" in client["providers"], "Microsoft federation is not enabled for this client"
host = urlparse(domain).hostname
suffix = ".auth." + region + ".amazoncognito.com"
domain_name = host[:-len(suffix)] if host.endswith(suffix) else host
actual = aws("cognito-idp", "describe-user-pool-domain", "--domain", domain_name,
             "--query", "DomainDescription.{pool:UserPoolId,account:AWSAccountId,status:Status}")
assert actual == {"pool": pool, "account": account, "status": "ACTIVE"}, "Cognito domain does not match the target environment"
print("Verified target account, pool, client, active domain, callbacks and invited-account policy.")
