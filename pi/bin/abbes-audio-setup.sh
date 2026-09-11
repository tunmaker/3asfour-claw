#!/usr/bin/env bash
# Select the speakerphone for both directions, once, at boot.
#
# This used to be a negotiation. Over Bluetooth the speaker only ever paired as a
# headset, so PipeWire gave it HSP -- 8 kHz mono, quiet and muffled -- and A2DP
# was never offered; forcing the profile needed a re-pair, the re-pair needed the
# speaker in pairing mode, and the adapter wedged on the way. A cable fixed that
# and brought its own: output went to the 3.5mm jack while input came from a
# webcam across the room, two devices that could not hear each other, which is
# why the microphone had to be muted for every word Abbes said.
#
# A USB speakerphone is one device doing both. It cancels its own output in
# hardware, so nothing needs muting, and it enumerates the same way every boot,
# so nothing needs re-pairing. What is left is choosing it and setting a level.
set -uo pipefail

CONF="$HOME/.config/voicepi/voicepi.env"
[ -r "$CONF" ] && { set -a; . "$CONF"; set +a; }

for _ in $(seq 30); do
    pactl info >/dev/null 2>&1 && break
    sleep 2
done
pactl info >/dev/null 2>&1 || { echo "pipewire not ready" >&2; exit 1; }

SINK="${SPEAKER_SINK:-}"
[ -n "$SINK" ] || SINK=$(pactl list sinks short 2>/dev/null | awk '/usb.*[Jj]abra/ {print $2; exit}')
[ -n "$SINK" ] || { echo "no USB speakerphone sink found; set SPEAKER_SINK" >&2; exit 1; }

SOURCE="${MIC_SOURCE:-}"
[ -n "$SOURCE" ] || SOURCE=$(pactl list sources short 2>/dev/null | awk '/alsa_input.*usb.*[Jj]abra/ {print $2; exit}')
[ -n "$SOURCE" ] || { echo "no USB speakerphone source found; set MIC_SOURCE" >&2; exit 1; }

# Defaults matter beyond this loop: the Jellyfin player and anything else that
# makes noise on this Pi follow them, and nothing should come out of the jack
# now that there is no speaker on it.
pactl set-default-sink "$SINK" 2>/dev/null || true
pactl set-default-source "$SOURCE" 2>/dev/null || true

pactl set-sink-volume "$SINK" "${SPEAKER_BOOT_VOLUME:-60}%" 2>/dev/null || true
pactl set-sink-mute "$SINK" 0 2>/dev/null || true
pactl set-source-mute "$SOURCE" 0 2>/dev/null || true

echo "output: $SINK"
echo "input:  $SOURCE"
echo "volume pinned: $(pactl get-sink-volume "$SINK" 2>/dev/null | head -1 | grep -o '[0-9]*%' | head -1)"
