#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root so it can read the protected runner configuration." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"
forge_runner_load_config /etc/amination-forge/runner.env

systemctl status amination-forge-runner.service --no-pager || true
echo
echo "Local readiness:"
curl --silent --show-error \
  "http://127.0.0.1:${FORGE_RUNNER_PORT}/healthz" || true
echo
