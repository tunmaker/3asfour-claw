#!/usr/bin/env bash
set -uo pipefail

MAC="${1:-${BT_SPEAKER_MAC:-}}"
[ -z "$MAC" ] && { echo "usage: bt-audio-test.sh <MAC>" >&2; exit 2; }

CARD="bluez_card.${MAC//:/_}"
SECONDS_TO_RECORD="${RECORD_SECONDS:-8}"

level() {
    python3 -c '
import wave, array, math, sys
w = wave.open(sys.argv[1]); n = w.getnframes()
a = array.array("h"); a.frombytes(w.readframes(n))
if not a:
    print("EMPTY"); raise SystemExit
peak = max(abs(x) for x in a)
rms = math.sqrt(sum(float(x) * x for x in a) / len(a))
db = lambda v: 20 * math.log10(v / 32768.0) if v else float("-inf")
print(f"secs={n/w.getframerate():.1f} peak={peak} ({db(peak):.1f} dBFS) rms={rms:.1f} ({db(rms):.1f} dBFS)")
' "$1"
}

echo "--- playback (A2DP) ---"
pactl set-card-profile "$CARD" a2dp-sink
sleep 2
python3 -c '
import math, struct, wave
w = wave.open("/tmp/bt-tone.wav", "w")
w.setnchannels(2); w.setsampwidth(2); w.setframerate(48000)
w.writeframes(b"".join(struct.pack("<hh", v, v) for v in
    (int(12000 * math.sin(2 * math.pi * 440 * i / 48000)) for i in range(48000 * 3))))
w.close()'
time pw-play --target="bluez_output.${MAC//:/_}.1" /tmp/bt-tone.wav

echo "--- capture (HFP) ---"
pactl set-card-profile "$CARD" headset-head-unit
sleep 3
SRC=$(pactl list sources short | awk '/bluez_input/ {print $1; exit}')
[ -z "$SRC" ] && { echo "no bluez_input source" >&2; exit 1; }
echo "speak now, ${SECONDS_TO_RECORD}s..."
timeout "$((SECONDS_TO_RECORD + 1))" pw-record --target="$SRC" /tmp/bt-rec.wav
level /tmp/bt-rec.wav

echo "--- sco errors ---"
dmesg 2>/dev/null | grep -c "Frame reassembly failed" || true

rm -f /tmp/bt-tone.wav /tmp/bt-rec.wav
