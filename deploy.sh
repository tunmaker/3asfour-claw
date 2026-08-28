#!/usr/bin/env bash
# Install this checkout into the running system.
# Run as the service user on the host that runs the assistant.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/bin"
UNIT_DIR="$HOME/.config/systemd/user"
WORKSPACE="${OPENCLAW_WORKSPACE:-$HOME/.openclaw/workspace}"

changed=0
note() { printf '  %s\n' "$*"; }

install_file() {
    local src="$1" dest="$2" mode="$3"
    if [ -f "$dest" ] && cmp -s "$src" "$dest"; then
        return 0
    fi
    install -m "$mode" "$src" "$dest"
    note "updated ${dest#$HOME/}"
    changed=$((changed + 1))
}

echo "Installing from $REPO"

mkdir -p "$BIN_DIR"
for f in "$REPO"/bin/*.sh "$REPO"/bin/*.py; do
    [ -e "$f" ] || continue
    case "$(basename "$f")" in
        _*) mode=644 ;;
        *)  mode=755 ;;
    esac
    install_file "$f" "$BIN_DIR/$(basename "$f")" "$mode"
done

mkdir -p "$UNIT_DIR" "$UNIT_DIR/openclaw-gateway.service.d"
for f in "$REPO"/systemd/*.service "$REPO"/systemd/*.timer; do
    [ -e "$f" ] || continue
    install_file "$f" "$UNIT_DIR/$(basename "$f")" 644
done
if [ -f "$REPO/systemd/openclaw-gateway.override.conf" ]; then
    install_file "$REPO/systemd/openclaw-gateway.override.conf" \
        "$UNIT_DIR/openclaw-gateway.service.d/override.conf" 644
fi

# Prompt and skills. USER.md and MEMORY.md are private and never in the repo,
# so they are left untouched here.
mkdir -p "$WORKSPACE/skills"
for f in "$REPO"/abbes/*.md; do
    [ -e "$f" ] || continue
    install_file "$f" "$WORKSPACE/$(basename "$f")" 644
done
for d in "$REPO"/abbes/skills/*/; do
    [ -d "$d" ] || continue
    name=$(basename "$d")
    mkdir -p "$WORKSPACE/skills/$name"
    install_file "$d/SKILL.md" "$WORKSPACE/skills/$name/SKILL.md" 644
done

if [ "$changed" -gt 0 ]; then
    systemctl --user daemon-reload
    echo "$changed file(s) updated; systemd reloaded."
    echo "Restart the gateway if the prompt or units changed:"
    echo "  systemctl --user restart openclaw-gateway"
else
    echo "Already up to date; nothing changed."
fi
