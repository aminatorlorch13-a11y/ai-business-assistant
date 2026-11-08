#!/usr/bin/env bash
set -Eeuo pipefail

SERVICE="amination-forge-runner"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

if [[ ! -f /etc/amination-forge/runner.env ]]; then
  echo "Runner configuration is missing. Run install-host.sh first." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"
forge_runner_load_config /etc/amination-forge/runner.env
PORT="$FORGE_RUNNER_PORT"

systemctl enable --now "$SERVICE.service"

for attempt in $(seq 1 20); do
  if curl --fail --silent --show-error \
      "http://127.0.0.1:${PORT}/healthz"; then
    echo
    echo "Forge runner is ready."
    exit 0
  fi
  sleep 2
done

echo "Runner did not become ready. Recent service logs:" >&2
journalctl -u "$SERVICE.service" -n 60 --no-pager >&2
exit 1
