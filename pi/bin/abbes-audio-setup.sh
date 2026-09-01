#!/usr/bin/env bash
# Select the output and pin its level, once, at boot.
#
# Output is the Pi's own 3.5mm jack, wired to the speaker's aux input. It was
# Bluetooth until the Bluetooth stopped being worth it: the speaker had only
# ever paired as a headset, so PipeWire gave it the HSP profile -- 8 kHz mono,
# quiet and muffled -- and A2DP was never even offered. Forcing the profile
# needed a re-pair, the re-pair needed the speaker in pairing mode, and the
# adapter wedged on the way (hci0 DOWN, "Connection timed out"). A cable has
# none of those states.
#
# What that removes, besides the noise: a device that renegotiates its profile
# on reconnect, a sink whose name changes with it, an auto-switch to headset
# whenever anything opens a microphone, and a speaker that restores its own
# saved volume behind us.
set -uo pipefail

CONF="$HOME/.config/voicepi/voicepi.env"
[ -r "$CONF" ] && { set -a; . "$CONF"; set +a; }

for _ in $(seq 30); do
    pactl info >/dev/null 2>&1 && break
    sleep 2
done
pactl info >/dev/null 2>&1 || { echo "pipewire not ready" >&2; exit 1; }

# Default to the onboard analog output. SPEAKER_SINK overrides it, which is the
# hook for plugging in a USB DAC later without editing this.
SINK="${SPEAKER_SINK:-}"
if [ -z "$SINK" ]; then
    SINK=$(pactl list sinks short 2>/dev/null | awk '/alsa_output.*mailbox/ {print $2; exit}')
fi
[ -n "$SINK" ] || { echo "no analog sink found" >&2; exit 1; }

pactl set-default-sink "$SINK" 2>/dev/null || true

# The jack routes to headphones rather than HDMI. On this board that is a card
# control, not a PipeWire one, so it is set here and not left to chance.
amixer -c 0 cset numid=3 1 >/dev/null 2>&1 || true

pactl set-sink-volume "$SINK" "${SPEAKER_BOOT_VOLUME:-50}%" 2>/dev/null || true
pactl set-sink-mute "$SINK" 0 2>/dev/null || true

echo "audio ready: $SINK"
echo "volume pinned: $(pactl get-sink-volume "$SINK" 2>/dev/null | head -1 | grep -o '[0-9]*%' | head -1)"
