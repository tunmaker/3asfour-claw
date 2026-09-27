#!/usr/bin/env bash
# Build the Baby Buddy MCP server image from source; it publishes none.
set -euo pipefail

REPO="${BABYBUDDY_MCP_REPO:-https://github.com/babybuddy/babybuddy-mcp.git}"
REF="${BABYBUDDY_MCP_REF:-85d2e020afb19d04d1e7b4db3e95ceb937f28c56}"
SRC="${BABYBUDDY_MCP_SRC:-$HOME/src/babybuddy-mcp}"

if [ ! -d "$SRC/.git" ]; then
    mkdir -p "$(dirname "$SRC")"
    git clone "$REPO" "$SRC"
fi

git -C "$SRC" fetch --quiet origin
git -C "$SRC" checkout --quiet --detach "$REF"

podman build --network=host -t "babybuddy-mcp:${REF:0:12}" -t babybuddy-mcp:latest "$SRC"

echo "Built localhost/babybuddy-mcp:latest from ${REF:0:12}"
echo "Restart it with: systemctl --user restart babybuddy-mcp"
