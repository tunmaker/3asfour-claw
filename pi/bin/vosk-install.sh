#!/usr/bin/env bash
# Installs Vosk and one small offline model for wake-word spotting. Nothing here
# talks to the network again once it has run.
set -euo pipefail

VENV="${VOSK_VENV:-$HOME/vosk}"
MODEL_DIR="${VOSK_MODEL_DIR:-$HOME/vosk/models}"
MODEL="${VOSK_MODEL_NAME:-vosk-model-small-ar-tn-0.1-linto}"
BASE=https://alphacephei.com/vosk/models

if [ ! -x "$VENV/bin/python" ]; then
    echo "creating venv at $VENV"
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet vosk

mkdir -p "$MODEL_DIR"
if [ ! -d "$MODEL_DIR/$MODEL" ]; then
    echo "downloading $MODEL"
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    curl -fSL --retry 3 -o "$tmp/m.zip" "$BASE/$MODEL.zip"
    unzip -q "$tmp/m.zip" -d "$MODEL_DIR"
fi

echo
echo "vosk:  $("$VENV/bin/python" -c 'import vosk; print(vosk.__file__)')"
echo "model: $MODEL_DIR/$MODEL  ($(du -sh "$MODEL_DIR/$MODEL" | cut -f1) on disk)"
echo
echo "Add to ~/.config/voicepi/voicepi.env:"
echo "  WAKE_VOSK_PYTHON=$VENV/bin/python"
echo "  WAKE_MODEL=$MODEL_DIR/$MODEL"
