#!/usr/bin/env bash
# Builds the React frontend and copies it into agent/frontend_dist, where
# fast_api_app.py's _mount_frontend() serves it and the Dockerfile's COPY
# picks it up. Run before `agents-cli deploy` — the Cloud Run build context
# is agent/, so frontend/ is not visible to Docker unless staged here first.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$AGENT_DIR")"
FRONTEND_DIR="$REPO_ROOT/frontend"

(cd "$FRONTEND_DIR" && npm ci && npm run build)

rm -rf "$AGENT_DIR/frontend_dist"
cp -r "$FRONTEND_DIR/dist" "$AGENT_DIR/frontend_dist"
# Keep the tracked placeholder alive across rebuilds (rm -rf above deletes
# it) so a clone that has run this script still Docker COPYs successfully
# even after `git clean`.
touch "$AGENT_DIR/frontend_dist/.gitkeep"

echo "Built frontend into $AGENT_DIR/frontend_dist"
