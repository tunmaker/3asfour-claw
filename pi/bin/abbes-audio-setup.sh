#!/usr/bin/env bash
set -uo pipefail

CONF="$HOME/.config/voicepi/voicepi.env"
[ -r "$CONF" ] && { set -a; . "$CONF"; set +a; }

MAC="${BT_SPEAKER_MAC:-}"
[ -n "$MAC" ] || { echo "no BT_SPEAKER_MAC set — nothing to pair"; exit 0; }

CARD="bluez_card.${MAC//:/_}"

for _ in $(seq 30); do
    pactl info >/dev/null 2>&1 && break
    sleep 2
done
pactl info >/dev/null 2>&1 || { echo "pipewire not ready" >&2; exit 1; }

"$HOME/bin/bt-pair.sh" "$MAC" || exit 1

for _ in $(seq 15); do
    pactl list cards short 2>/dev/null | grep -q "$CARD" && break
    sleep 2
done
pactl list cards short 2>/dev/null | grep -q "$CARD" || { echo "no bluez card after pairing" >&2; exit 1; }

pactl set-card-profile "$CARD" "${BT_PROFILE:-a2dp-sink}" || true
sink="bluez_output.${MAC//:/_}.1"
pactl set-default-sink "$sink" 2>/dev/null || true

# The speaker restores its own saved level on every reconnect, so an unpinned volume
# drifts: a reboot or a wireplumber restart silently leaves Abbes too quiet to hear.
pactl set-sink-volume "$sink" "${SPEAKER_BOOT_VOLUME:-85}%" 2>/dev/null || true
pactl set-sink-mute "$sink" 0 2>/dev/null || true

echo "audio ready: $(pactl list sinks short | grep bluez || echo 'no bluez sink')"
echo "volume pinned: $(pactl get-sink-volume "$sink" 2>/dev/null | head -1 | grep -o '[0-9]*%' | head -1)"
