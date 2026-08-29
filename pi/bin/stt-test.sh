#!/usr/bin/env bash
set -uo pipefail

CONF="$HOME/.config/voicepi/voicepi.env"
[ -r "$CONF" ] && { set -a; . "$CONF"; set +a; }

WHISPER_URL="${WHISPER_URL:?WHISPER_URL must be set in ~/.config/voicepi/voicepi.env}"
MIC_SOURCE="${MIC_SOURCE:-@DEFAULT_SOURCE@}"
SECS="${1:-8}"
LANG_HINT="${2:-${WHISPER_LANGUAGE:-ar}}"
CLIP=$(mktemp /tmp/stt-XXXXXX.wav)
NORM=$(mktemp /tmp/stt-XXXXXX.wav)
trap 'rm -f "$CLIP" "$NORM"' EXIT

echo "recording ${SECS}s from ${MIC_SOURCE} — speak now"
for i in 3 2 1; do printf '\r  starting in %s...' "$i"; sleep 1; done
printf '\r  GO                    \n'
timeout "$((SECS + 1))" pw-record --target="$MIC_SOURCE" --rate=16000 --channels=1 --format=s16 "$CLIP"

python3 - "$CLIP" "$NORM" <<'PY'
import wave, array, math, sys
w = wave.open(sys.argv[1]); n = w.getnframes(); sr = w.getframerate()
a = array.array("h"); a.frombytes(w.readframes(n))
db = lambda v: 20 * math.log10(v / 32768.0) if v else float("-inf")
peak = max(abs(x) for x in a); rms = math.sqrt(sum(float(x) * x for x in a) / len(a))
print(f"  level: peak={db(peak):.1f} dBFS rms={db(rms):.1f} dBFS")
if db(rms) < -45:
    print("  WARNING: very quiet — whisper will likely hallucinate. Speak closer or raise the mic gain.")
gain = min(20.0, (10 ** (-24 / 20) * 32768) / max(rms, 1))
if peak * gain > 32000:
    gain = 32000 / peak
o = wave.open(sys.argv[2], "w"); o.setnchannels(1); o.setsampwidth(2); o.setframerate(sr)
o.writeframes(array.array("h", [max(-32768, min(32767, int(x * gain))) for x in a]).tobytes()); o.close()
print(f"  normalized x{gain:.2f} -> rms=-24.0 dBFS")
PY

echo "transcribing (language=${LANG_HINT})..."
curl -sS --fail-with-body -m "${WHISPER_TIMEOUT:-120}" "$WHISPER_URL" \
    -F "file=@${NORM}" \
    -F "language=${LANG_HINT}" \
    ${WHISPER_PROMPT:+-F "prompt=${WHISPER_PROMPT}"} \
    -F "response_format=json" \
| python3 -c 'import sys,json; print("TRANSCRIPT:", (json.load(sys.stdin).get("text") or "").strip())'
