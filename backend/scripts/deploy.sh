#!/usr/bin/env bash
# ============================================================
# Drishti deployment script
#
# Local build + remote rollout via docker compose.
# Configure via environment variables:
#   REMOTE_HOST   e.g. deploy@prod.drishti.ai      (required for remote mode)
#   IMAGE_TAG     e.g. registry.example.com/drishti:1.2.0
#   DEPLOY_DIR    path on remote, default /srv/drishti
#
# Usage:
#   ./scripts/deploy.sh local    # rebuild & restart the compose stack locally
#   IMAGE_TAG=... ./scripts/deploy.sh push    # build + push image
#   ./scripts/deploy.sh remote   # ssh rollout (pull + migrate + up)
# ============================================================
set -euo pipefail

MODE="${1:-local}"
IMAGE_TAG="${IMAGE_TAG:-drishti:local}"
DEPLOY_DIR="${DEPLOY_DIR:-/srv/drishti}"
COMPOSE="docker compose"

log() { printf '\n[deploy] %s\n' "$*"; }

wait_healthy() {
  local url="$1"
  log "Waiting for health endpoint: $url"
  for _ in $(seq 1 30); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "Service healthy."
      return 0
    fi
    sleep 2
  done
  log "ERROR: health check failed"
  exit 1
}

case "$MODE" in
  local)
    log "Building image ${IMAGE_TAG}"
    $COMPOSE build api
    log "Starting stack (postgres/redis/api)"
    $COMPOSE up -d
    wait_healthy "http://localhost:8000/health"
    log "Local deploy complete. Docs: http://localhost:8000/docs"
    ;;

  push)
    log "Building ${IMAGE_TAG}"
    docker build -t "${IMAGE_TAG}" .
    if [[ -n "${REMOTE_REGISTRY_LOGIN:-}" ]]; then
      echo "${REMOTE_REGISTRY_PASSWORD:?}" | docker login "$REMOTE_REGISTRY_LOGIN" --password-stdin
    fi
    docker push "${IMAGE_TAG}"
    log "Pushed ${IMAGE_TAG}"
    ;;

  remote)
    : "${REMOTE_HOST:?Set REMOTE_HOST for remote deploys}"
    log "Rolling out on ${REMOTE_HOST}:${DEPLOY_DIR}"
    ssh "$REMOTE_HOST" bash -s <<EOF
set -euo pipefail
cd "${DEPLOY_DIR}"
export IMAGE_TAG="${IMAGE_TAG}"
${COMPOSE} pull api || true
${COMPOSE} up -d --no-deps postgres redis
sleep 5
${COMPOSE} up -d api
EOF
    wait_healthy "http://${REMOTE_HOST}/health"
    log "Remote deploy complete."
    ;;

  *)
    echo "Usage: $0 {local|push|remote}" >&2
    exit 2
    ;;
esac
