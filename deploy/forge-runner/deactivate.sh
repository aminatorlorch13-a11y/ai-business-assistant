#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

systemctl disable --now amination-forge-runner.service
echo "Runner stopped and disabled. Data and configuration were preserved."
