#!/usr/bin/env bash
set -uo pipefail

MAC="${1:-${BT_SPEAKER_MAC:-}}"
if [ -z "$MAC" ]; then
    echo "usage: bt-pair.sh <MAC>   (or set BT_SPEAKER_MAC)" >&2
    exit 2
fi

echo "--- discovering ---"
bluetoothctl --timeout 12 scan on >/dev/null 2>&1
bluetoothctl devices | grep -i "$MAC" || { echo "device $MAC not found in scan" >&2; exit 1; }

echo "--- pairing ---"
bluetoothctl --agent NoInputNoOutput pair "$MAC" 2>&1 | tail -3

echo "--- trusting ---"
bluetoothctl trust "$MAC" 2>&1 | tail -1

echo "--- connecting ---"
bluetoothctl connect "$MAC" 2>&1 | tail -3

sleep 3
echo "--- device state ---"
bluetoothctl info "$MAC" 2>&1 | grep -E 'Name|Paired|Trusted|Connected|UUID: (Audio|Handsfree|Headset|Advanced)'
