#!/usr/bin/env bash
# deploy.sh — sync DragonEyes to Raspberry Pi via rsync
#
# Usage:
#   ./deploy.sh                 # uses PI_HOST env var or prompts
#   ./deploy.sh pi@192.168.1.42
#   PI_HOST=pi@192.168.1.42 ./deploy.sh

set -euo pipefail

REMOTE="${1:-${PI_HOST:-}}"

if [[ -z "$REMOTE" ]]; then
  read -rp "Pi user@host (e.g. pi@192.168.1.42): " REMOTE
fi

REMOTE_DIR="/home/${REMOTE%%@*}/DragonEyes"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "→ Deploying to ${REMOTE}:${REMOTE_DIR}"

rsync -avz --progress \
  --exclude='venv/' \
  --exclude='.venv*/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.git/' \
  --exclude='mock/' \
  --exclude='notes/' \
  --exclude='*.egg-info/' \
  --exclude='.DS_Store' \
  --exclude='run_dev.py' \
  --exclude='CLAUDE.md' \
  --exclude='deploy.sh' \
  "${SCRIPT_DIR}/" \
  "${REMOTE}:${REMOTE_DIR}/"

echo "✓ Done — ${REMOTE}:${REMOTE_DIR}"
