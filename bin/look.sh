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
# Full answers go to Qwen with its projector, on the slot reserved for image
# prefills so that a 1024-token image cannot evict the voice session's cached
# prefix. --quick uses the small captioner instead, which is for the presence
# gate and describes furniture adequately and little else.
#
# --photo saves the frame under $ABBES_DATA_DIR/camera and prints the path as
# a "MEDIA:<path>" line after the answer. The agent copies that line verbatim
# into its reply, on its own line, and the channel attaches the picture. Only
# the last 20 shots are kept.
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
    dir="${ABBES_DATA_DIR:-/var/lib/abbes}/camera"
    mkdir -p "$dir"
    shot="$dir/look-$(date +%Y%m%d-%H%M%S).jpg"
    if ! curl -sS --fail --max-time 30 "$base/vision/snapshot" -o "$shot"; then
        rm -f "$shot"
        echo "could not fetch a frame; is the camera running?" >&2
        exit 1
    fi
    ls -1t "$dir"/look-*.jpg 2>/dev/null | tail -n +21 | xargs -r rm -f
fi

payload=$(python3 -c '
import json, sys
print(json.dumps({"prompt": sys.argv[1], "quick": sys.argv[2] == "true"}))' "$prompt" "$quick")

response=$(curl -sS --max-time 180 "$base/vision/look" -H "Content-Type: application/json" -d "$payload")

printf '%s' "$response" | python3 -c '
import json, sys
d = json.load(sys.stdin)
err = d.get("error")
if err:
    sys.stderr.write("could not look: " + str(err) + "\n")
    raise SystemExit(1)
print(d.get("answer", ""))'

if $photo; then
    printf '\nTo attach the picture, put this on its own line in your reply:\nMEDIA:%s\n' "$shot"
fi
