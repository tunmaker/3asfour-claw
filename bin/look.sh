#!/usr/bin/env bash
# Look through the camera and answer a question about what is there.
#
#   look.sh                          "what do you see?"
#   look.sh "هل الباب مفتوح؟"        any question, any language
#   look.sh --quick "is anyone there" the 256M model: fast, blunt
#
# There is no shutter. The Pi already sends a frame every few seconds, so the
# newest one is seconds old at worst and asking for another would add latency
# for nothing. "Take a picture" is answered from that.
#
# Full answers go to Qwen with its projector, on the slot reserved for image
# prefills so that a 1024-token image cannot evict the voice session's cached
# prefix. --quick uses the small captioner instead, which is for the presence
# gate and describes furniture adequately and little else.
set -euo pipefail
set -a; . "$HOME/.openclaw/openclaw.env"; set +a

quick=false
if [ "${1:-}" = "--quick" ]; then
    quick=true
    shift
fi
prompt="${1:-Describe what you see in this image, briefly.}"

url="${ABBES_ORCH_URL:-http://127.0.0.1:18790}/vision/look"

payload=$(python3 -c '
import json, sys
print(json.dumps({"prompt": sys.argv[1], "quick": sys.argv[2] == "true"}))' "$prompt" "$quick")

response=$(curl -sS --max-time 180 "$url" -H "Content-Type: application/json" -d "$payload")

printf '%s' "$response" | python3 -c '
import json, sys
d = json.load(sys.stdin)
err = d.get("error")
if err:
    sys.stderr.write("could not look: " + str(err) + "\n")
    raise SystemExit(1)
print(d.get("answer", ""))'
