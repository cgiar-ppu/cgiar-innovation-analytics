#!/bin/bash
# ===========================================================================
# CGIAR Innovation Analytics -- Production entrypoint
# ===========================================================================
# Wraps the uvicorn app with litestream so chat history is durable:
#   1. Ensure the .synapsis data dir exists (it is bind-mounted from the host
#      at /opt/cgiar-ia/synapsis -> /workspace/.synapsis, so it already
#      survives `docker rm` + `docker run`).
#   2. If a litestream S3 replica exists, restore chat.db before starting.
#   3. Run uvicorn under `litestream replicate -exec` so every write is
#      streamed to S3 (cross-instance / cross-AZ durability).
# ===========================================================================
set -e

echo "=== Synapsis Startup (prod entrypoint) ==="

# Ensure the synapsis data directory exists (bind-mounted from host).
mkdir -p /workspace/.synapsis

# uvicorn command must match the original Dockerfile.prod CMD exactly.
APP_CMD="python -m uvicorn app:app --host 0.0.0.0 --port ${SYNAPSIS_PORT:-7780}"

if [ -n "${LITESTREAM_S3_BUCKET}" ]; then
  echo "Litestream: attempting restore from s3://${LITESTREAM_S3_BUCKET}/litestream/chat.db ..."
  # -if-replica-exists makes the first-ever run a no-op (fresh DB) instead of
  # an error. -if-db-not-exists avoids clobbering a DB already present on the
  # bind-mounted host volume.
  if litestream restore -if-replica-exists -if-db-not-exists \
        -config /etc/litestream.yml /workspace/.synapsis/chat.db; then
    echo "Litestream: restore complete (or DB already present / no replica yet)"
  else
    echo "Litestream: restore reported no existing replica — starting fresh"
  fi

  echo "Litestream: starting replication and app..."
  exec litestream replicate -config /etc/litestream.yml -exec "${APP_CMD}"
else
  echo "LITESTREAM_S3_BUCKET not set — starting app without replication"
  exec ${APP_CMD}
fi
