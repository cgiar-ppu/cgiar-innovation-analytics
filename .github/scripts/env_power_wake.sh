#!/usr/bin/env bash
# Env-power "wake and hold" for EC2 deploys (AWS cost sprint, Nov 2026).
#
# The env-power controller may have stopped this environment's EC2 instance
# (dev/test sleep when unused). SSM deploys need a running server, so before
# deploying: wake it, wait until healthy, then keep it visibly in use for the
# rest of the job. A NO-OP when the environment is awake (first probe answers 200)
# or the controller is not enrolled.
#
#   env_power_wake.sh <base_url> <health_path> <instance_id|-> [timeout_s]
#
# 1. GET <base_url><health_path> until 200, with `X-Env-Power-Wake: ci`. While the env
#    sleeps, the load balancer routes to the controller's wake responder, which treats
#    that header as a real wake (never bot-filtered) and answers 503 until the app is up.
# 2. Fallback (no controller, or a manual stop): if the instance is still
#    'stopped' after 90 s, start it with the deploy role (the workflow already
#    holds ec2 rights). The controller treats "healthy while asleep" as awake.
# 3. Hold: a background GET every 4 min with `X-Env-Power-Hold: 1` until the job
#    ends (GitHub kills it then). The app counts it as activity, so together with
#    the controller's 60-min idle rule and its CloudFormation-in-progress guard
#    the server stays up for the deploy and the post-deploy checks.
set -uo pipefail

BASE="${1:-}"; HEALTH="${2:-/api/health}"; IID="${3:--}"; TIMEOUT="${4:-420}"
if [ -z "$BASE" ] || [ "$BASE" = "None" ]; then
  echo "env-power: no URL for this stack (first deploy?) -> nothing to wake"; exit 0
fi
URL="${BASE%/}${HEALTH}"
UA="env-power-deploy/1 (github-actions ${GITHUB_REPOSITORY:-local} run ${GITHUB_RUN_ID:-0})"
probe() {
  local c
  # X-Env-Power-Wake: ci = the controller's "real wake, never bot-filtered" marker (E3 contract).
  c=$(curl -s -o /dev/null -w "%{http_code}" -m 10 -A "$UA" -H "X-Env-Power-Wake: ci" -H "X-Env-Power-Hold: 1" "$URL" 2>/dev/null)
  echo "${c:-000}"
}
state() {
  [ "$IID" = "-" ] && { echo unknown; return; }
  aws ec2 describe-instances --instance-ids "$IID" --query "Reservations[0].Instances[0].State.Name" \
    --output text 2>/dev/null || echo unknown
}

t0=$(date +%s); started=0
code=$(probe)
if [ "$code" = "200" ]; then
  echo "env-power: $URL already healthy -> no wake needed"
else
  echo "env-power: $URL answered $code (instance: $(state)) -> waking, up to ${TIMEOUT}s"
  while :; do
    el=$(( $(date +%s) - t0 ))
    code=$(probe)
    if [ "$code" = "200" ]; then echo "env-power: healthy after ${el}s"; break; fi
    st=$(state)
    if [ "$started" = 0 ] && [ "$el" -ge 90 ] && [ "$st" = "stopped" ]; then
      echo "::warning::env-power: instance $IID still stopped after ${el}s (no wake responder?) -> starting it"
      aws ec2 start-instances --instance-ids "$IID" >/dev/null && started=1
    fi
    if [ "$el" -ge "$TIMEOUT" ]; then
      echo "::error::env-power: $URL not healthy after ${TIMEOUT}s (last HTTP $code, instance $st). Not deploying onto a server that is not running."
      exit 1
    fi
    echo "  ${el}s: HTTP $code, instance $st"
    sleep 10
  done
fi

# Hold for the rest of the job (orphan processes are killed when the job ends).
nohup bash -c "while :; do sleep 240; curl -s -o /dev/null -m 10 -A '$UA' -H 'X-Env-Power-Hold: 1' '$URL' || true; done" \
  >/dev/null 2>&1 &
echo "env-power: hold active (keep-alive every 4 min until the job ends)"
