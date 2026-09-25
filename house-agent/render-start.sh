#!/usr/bin/env bash
# Start command for Render's native Python runtime.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

export HOUSE_AGENT_FRONTEND_DIST="${HOUSE_AGENT_FRONTEND_DIST:-$here/frontend/dist}"
export HOST="${HOST:-0.0.0.0}"

# The database lives on the persistent disk at /data.
if [ -z "${HOUSE_AGENT_DATABASE_URL:-}" ]; then
  data_dir=/data
  db="$data_dir/house-agent.sqlite3"
  legacy="$data_dir/house_agent.db"
  if [ ! -e "$db" ] && [ -e "$legacy" ]; then
    if [ -w "$legacy" ]; then
      db="$legacy"
    else
      # Created by the earlier Docker build (as root), so this user can't write it.
      # Keep a copy we own and use that from now on; the original stays as a backup.
      echo "==> Copying $legacy to $db (the original isn't writable by $(id -un))"
      cp "$legacy" "$db"
      chmod u+w "$db"  # cp keeps the original's read-only mode
    fi
  fi
  if [ -e "$db" ] && [ ! -w "$db" ]; then
    echo "==> WARNING: $db is not writable by $(id -un); changes won't be saved" >&2
    ls -la "$data_dir" >&2 || true
  fi
  export HOUSE_AGENT_DATABASE_URL="sqlite:///$db"
fi
echo "==> Database: $HOUSE_AGENT_DATABASE_URL"

# One process only: the scheduler and search runs live in it. Render sets $PORT.
exec house-agent serve
