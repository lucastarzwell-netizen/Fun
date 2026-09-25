#!/usr/bin/env bash
# Start command for Render's native Python runtime.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

# Same defaults the Docker image sets. The database lives on the persistent disk at /data.
export HOUSE_AGENT_FRONTEND_DIST="${HOUSE_AGENT_FRONTEND_DIST:-$here/frontend/dist}"
export HOUSE_AGENT_DATABASE_URL="${HOUSE_AGENT_DATABASE_URL:-sqlite:////data/house_agent.db}"
export HOST="${HOST:-0.0.0.0}"

# One process only: the scheduler and search runs live in it. Render sets $PORT.
exec house-agent serve
