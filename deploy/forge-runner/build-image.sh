#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/amination-ai}"
IMAGE="${FORGE_RUNNER_IMAGE:-amination-forge-runner:latest}"

if [[ ! -f "$PROJECT_DIR/app/forge/runner/Dockerfile" ]]; then
  echo "Forge runner Dockerfile not found in $PROJECT_DIR" >&2
  exit 1
fi

docker build \
  --pull \
  --file "$PROJECT_DIR/app/forge/runner/Dockerfile" \
  --tag "$IMAGE" \
  "$PROJECT_DIR/app/forge/runner"

echo "Built runner image: $IMAGE"
