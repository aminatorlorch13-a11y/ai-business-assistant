#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(realpath -m "${PROJECT_DIR:-/opt/amination-ai}")"
ENV_DIR="/etc/amination-forge"
ENV_FILE="$ENV_DIR/runner.env"
DATA_DIR="/var/lib/amination-forge"
SERVICE_NAME="amination-forge-runner"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

# The systemd service uses ProtectHome=true. Keep the project under /opt
# and reject unsafe paths before making any host changes.
if [[ "$PROJECT_DIR" != /opt/* || ! "$PROJECT_DIR" =~ ^/opt/[A-Za-z0-9_./-]+$ ]]; then
  echo "PROJECT_DIR must be under /opt and contain only letters, numbers, dots, underscores, slashes or hyphens." >&2
  exit 1
fi

if [[ ! -f "$PROJECT_DIR/app/forge/runner/server.py" ||
      ! -f "$PROJECT_DIR/app/forge/runner/Dockerfile" ||
      ! -f "$PROJECT_DIR/requirements.txt" ||
      ! -f "$PROJECT_DIR/deploy/forge-runner/config.sh" ]]; then
  echo "Amination AI source files are missing from $PROJECT_DIR." >&2
  echo "Copy the repository there before preparing the host." >&2
  exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer currently supports Debian/Ubuntu hosts only." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  ca-certificates \
  curl \
  docker.io \
  python3 \
  python3-pip \
  python3-venv

systemctl enable --now docker

if ! getent group docker >/dev/null; then
  groupadd docker
fi

install -d -o root -g root -m 0755 "$DATA_DIR"

if ! id forge-runner >/dev/null 2>&1; then
  useradd \
    --system \
    --create-home \
    --home-dir "$DATA_DIR/home" \
    --shell /usr/sbin/nologin \
    forge-runner
fi

usermod -aG docker forge-runner

install -d -o forge-runner -g forge-runner -m 0700 "$DATA_DIR"
install -d -o forge-runner -g forge-runner -m 0700 "$DATA_DIR/home"
install -d -o root -g forge-runner -m 0750 "$ENV_DIR"

if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  python3 -m venv "$PROJECT_DIR/.venv"
fi

"$PROJECT_DIR/.venv/bin/python" -m pip install -r "$PROJECT_DIR/requirements.txt"

if [[ ! -f "$ENV_FILE" ]]; then
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  umask 077
  cat > "$ENV_FILE" <<EOF
FORGE_RUNNER_ROOT=$DATA_DIR
FORGE_RUNNER_IMAGE=amination-forge-runner:latest
FORGE_RUNNER_TOKEN=$TOKEN
FORGE_RUNNER_MEMORY=1g
FORGE_RUNNER_CPUS=2
FORGE_RUNNER_PIDS=128
FORGE_RUNNER_MAX_TIMEOUT=120
FORGE_RUNNER_MAX_CONCURRENT=2
FORGE_RUNNER_SESSION_TTL=1800
FORGE_RUNNER_HOST=127.0.0.1
FORGE_RUNNER_PORT=8765
EOF
else
  echo "Existing runner environment preserved: $ENV_FILE"
fi

chown root:forge-runner "$ENV_FILE"
chmod 0640 "$ENV_FILE"

# Apply the same strict configuration rules used by activation and status.
source "$PROJECT_DIR/deploy/forge-runner/config.sh"
forge_runner_load_config "$ENV_FILE"

PROJECT_DIR="$PROJECT_DIR" \
  bash "$PROJECT_DIR/deploy/forge-runner/build-image.sh"

PROJECT_DIR="$PROJECT_DIR" \
UNIT_SOURCE="$PROJECT_DIR/deploy/forge-runner/amination-forge-runner.service" \
UNIT_DEST="/etc/systemd/system/$SERVICE_NAME.service" \
python3 - <<'PYUNIT'
import os
import re
from pathlib import Path

project_dir = os.environ["PROJECT_DIR"]
if not project_dir.startswith("/opt/") or not re.fullmatch(r"/opt/[A-Za-z0-9_./-]+", project_dir):
    raise SystemExit("PROJECT_DIR must be under /opt and contain no spaces or special characters.")

source = Path(os.environ["UNIT_SOURCE"])
destination = Path(os.environ["UNIT_DEST"])
unit = source.read_text()

if "/opt/amination-ai" not in unit:
    raise SystemExit("Systemd project path placeholder was not found.")

destination.write_text(unit.replace("/opt/amination-ai", project_dir))
destination.chmod(0o644)
PYUNIT

systemctl daemon-reload
systemctl disable --now "$SERVICE_NAME.service" 2>/dev/null || true

echo
echo "Host preparation completed."
echo "Service installed but deliberately NOT enabled or started."
echo "Review: $ENV_FILE"
echo "Activate later with:"
echo "  bash $PROJECT_DIR/deploy/forge-runner/activate.sh"
