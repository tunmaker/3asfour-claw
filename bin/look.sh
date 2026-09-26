#!/usr/bin/env bash
# Look through the camera and answer a question about what is there.
#
#   look.sh                          "what do you see?"
#   look.sh "هل الباب مفتوح؟"        any question, any language
#   look.sh --quick "is anyone there" the 256M model: fast, blunt
#   look.sh --photo "what is this"   also save the frame and print a MEDIA:
#                                    line for attaching it to a chat reply
#
# There is no shutter. The Pi already sends a frame every few seconds, so the
# newest one is seconds old at worst and asking for another would add latency
# for nothing. "Take a picture" is answered from that.
#
# Full answers go to Qwen with its projector. --quick uses the small captioner
# instead, which is for the presence gate and describes furniture adequately
# and little else.
#
# --photo saves the frame under $ABBES_CAMERA_DIR (default ~/.openclaw/camera)
# and prints "MEDIA:<path>" for the model to copy verbatim into its reply.
# The directory must stay under $HOME: channel delivery loads local media
# only from the home directory and /tmp by default, and a shot parked in
# /var/lib/abbes reached WhatsApp as "Unavailable - Outside allowed folders".
# The filename is unique per shot, and must be: re-sending a path the
# session has already attached makes the gateway resolve it from session
# history, whose stored block has no inline data, and the reply shows
# "omitted image payload" instead of the picture (tried a fixed latest.jpg;
# the second send always broke). latest.jpg is still written as a
# convenience copy -- never attach it. The last 20 shots are kept. In photo
# mode the analysis is best effort with a shorter cap: the picture still
# ships when the vision lane is busy; it is the deliverable, the
# description is garnish.
set -euo pipefail
set -a; . "$HOME/.openclaw/openclaw.env"; set +a

quick=false
photo=false
while [ "${1:-}" = "--quick" ] || [ "${1:-}" = "--photo" ]; do
    [ "$1" = "--quick" ] && quick=true
    [ "$1" = "--photo" ] && photo=true
    shift
done
prompt="${1:-Describe what you see in this image, briefly.}"

base="${ABBES_ORCH_URL:-http://127.0.0.1:18790}"

shot=""
if $photo; then
    dir="${ABBES_CAMERA_DIR:-$HOME/.openclaw/camera}"
    mkdir -p "$dir"
    shot="$dir/look-$(date +%Y%m%d-%H%M%S)-$$.jpg"
    if ! curl -sS --fail --max-time 30 "$base/vision/snapshot" -o "$shot"; then
        rm -f "$shot"
        echo "could not fetch a frame; is the camera running?" >&2
        exit 1
    fi
    cp -f "$shot" "$dir/latest.jpg"
    ls -1t "$dir"/look-*.jpg 2>/dev/null | tail -n +21 | xargs -r rm -f
fi

look_timeout=180
$photo && look_timeout=60

payload=$(python3 -c '
import json, sys
print(json.dumps({"prompt": sys.argv[1], "quick": sys.argv[2] == "true"}))' "$prompt" "$quick")

answer_ok=true
response=$(curl -sS --max-time "$look_timeout" "$base/vision/look" \
    -H "Content-Type: application/json" -d "$payload") || answer_ok=false

if $answer_ok; then
    printf '%s' "$response" | python3 -c '
import json, sys
d = json.load(sys.stdin)
err = d.get("error")
if err:
    sys.stderr.write("could not look: " + str(err) + "\n")
    raise SystemExit(1)
print(d.get("answer", ""))' || answer_ok=false
fi

if ! $answer_ok; then
    $photo || exit 1
    echo "التحليل تعطّل الآن، لكن الصورة جاهزة."
fi

if $photo; then
    printf '\nTo attach the picture, copy this line into your reply EXACTLY as printed, on its own line. Do not change or reuse a filename:\nMEDIA:%s\n' "$shot"
fi
