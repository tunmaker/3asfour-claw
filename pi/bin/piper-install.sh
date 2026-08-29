#!/usr/bin/env bash
set -euo pipefail

PIPER_DIR="$HOME/piper"
PIPER_RELEASE="https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz"
VOICE_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main"

VOICES=(
    "ar_JO-kareem-medium ar/ar_JO/kareem/medium"
    "fr_FR-siwis-medium  fr/fr_FR/siwis/medium"
    "en_US-lessac-medium en/en_US/lessac/medium"
)

if [ ! -x "$PIPER_DIR/piper" ]; then
    tmp=$(mktemp -d)
    curl -sSL -o "$tmp/piper.tar.gz" "$PIPER_RELEASE"
    tar xzf "$tmp/piper.tar.gz" -C "$tmp"
    rm -rf "$PIPER_DIR"
    mv "$tmp/piper" "$PIPER_DIR"
    rm -rf "$tmp"
fi

install -d "$PIPER_DIR/voices"
for entry in "${VOICES[@]}"; do
    read -r name path <<<"$entry"
    for ext in onnx onnx.json; do
        [ -s "$PIPER_DIR/voices/$name.$ext" ] && continue
        curl -sSL -o "$PIPER_DIR/voices/$name.$ext" "$VOICE_BASE/$path/$name.$ext"
    done
done

export LD_LIBRARY_PATH="$PIPER_DIR"
echo "installed:"
ls -1 "$PIPER_DIR/voices/"*.onnx
echo "test:"
echo "باهي" | "$PIPER_DIR/piper" --model "$PIPER_DIR/voices/ar_JO-kareem-medium.onnx" --output_file /tmp/piper-check.wav
python3 -c 'import wave; w=wave.open("/tmp/piper-check.wav"); print(f"  ok: {w.getnframes()/w.getframerate():.2f}s @ {w.getframerate()}Hz")'
rm -f /tmp/piper-check.wav
