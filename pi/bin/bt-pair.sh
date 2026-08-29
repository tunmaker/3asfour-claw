#!/usr/bin/env bash
set -uo pipefail

MAC="${1:-${BT_SPEAKER_MAC:-}}"
if [ -z "$MAC" ]; then
    echo "usage: bt-pair.sh <MAC>   (or set BT_SPEAKER_MAC)" >&2
    exit 2
fi

paired() { bluetoothctl info "$MAC" 2>/dev/null | grep -q "Paired: yes"; }
connected() { bluetoothctl info "$MAC" 2>/dev/null | grep -q "Connected: yes"; }

if connected && paired; then
    echo "already paired and connected"
    exit 0
fi

# This speaker stores no link key, so a stale half-bond must be cleared before retrying.
paired || bluetoothctl remove "$MAC" >/dev/null 2>&1

echo "--- discovering ---"
bluetoothctl --timeout 12 scan on >/dev/null 2>&1
bluetoothctl devices | grep -qi "$MAC" || { echo "device $MAC not found; is it on and in pairing mode?" >&2; exit 1; }

echo "--- pairing ---"
bluetoothctl --agent NoInputNoOutput pair "$MAC" 2>&1 | tail -2
bluetoothctl trust "$MAC" >/dev/null 2>&1

echo "--- connecting ---"
for attempt in 1 2 3; do
    bluetoothctl connect "$MAC" 2>&1 | tail -1
    sleep 3
    connected && break
    echo "  retry $attempt"
done

echo "--- state ---"
bluetoothctl info "$MAC" 2>&1 | grep -E 'Name|Paired|Trusted|Connected'
pactl list cards short 2>/dev/null | grep bluez || echo "WARNING: no bluez card in PipeWire"
