#!/usr/bin/env bash

forge_runner_validate_config() {
  if [[ ! ${FORGE_RUNNER_ROOT+x} ]]; then FORGE_RUNNER_ROOT="/var/lib/amination-forge"; fi
  if [[ ! ${FORGE_RUNNER_HOST+x} ]]; then FORGE_RUNNER_HOST="127.0.0.1"; fi
  if [[ ! ${FORGE_RUNNER_PORT+x} ]]; then FORGE_RUNNER_PORT="8765"; fi
  if [[ ! ${FORGE_RUNNER_IMAGE+x} ]]; then FORGE_RUNNER_IMAGE="amination-forge-runner:latest"; fi

  if [[ "$FORGE_RUNNER_ROOT" != "/var/lib/amination-forge" ]]; then
    echo "FORGE_RUNNER_ROOT must be /var/lib/amination-forge." >&2
    return 1
  fi

  if [[ "$FORGE_RUNNER_HOST" != "127.0.0.1" ]]; then
    echo "FORGE_RUNNER_HOST must be 127.0.0.1. Public binding is prohibited." >&2
    return 1
  fi

  if [[ ! "$FORGE_RUNNER_PORT" =~ ^[0-9]{1,5}$ ]]; then
    echo "FORGE_RUNNER_PORT must be a number from 1 to 65535." >&2
    return 1
  fi

  local port_number=$((10#$FORGE_RUNNER_PORT))
  if (( port_number < 1 || port_number > 65535 )); then
    echo "FORGE_RUNNER_PORT must be a number from 1 to 65535." >&2
    return 1
  fi

  if [[ -z "$FORGE_RUNNER_IMAGE" || "$FORGE_RUNNER_IMAGE" =~ [[:space:]] ]]; then
    echo "FORGE_RUNNER_IMAGE must be non-empty and contain no whitespace." >&2
    return 1
  fi

  export FORGE_RUNNER_ROOT FORGE_RUNNER_HOST FORGE_RUNNER_PORT FORGE_RUNNER_IMAGE
}

forge_runner_load_config() {
  local env_file="${1:?Configuration file path is required}"

  if [[ ! -f "$env_file" ]]; then
    echo "Runner configuration is missing: $env_file" >&2
    return 1
  fi

  set -a
  . "$env_file"
  set +a

  forge_runner_validate_config
}
