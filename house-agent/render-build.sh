#!/usr/bin/env bash
# Build for Render's native Python runtime: the dashboard (Node) and the API (Python).
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v npm >/dev/null 2>&1; then
  echo "==> npm not found; installing Node.js with nodeenv"
  pip install --quiet nodeenv
  nodeenv --prebuilt --node=lts .node
  # shellcheck disable=SC1091
  source .node/bin/activate
fi

echo "==> Building the dashboard"
(cd frontend && npm ci && npm run build)

echo "==> Installing the API"
pip install ./backend
