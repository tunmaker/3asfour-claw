#!/usr/bin/env bash
set -euo pipefail

PATH="/usr/sbin:/sbin:$PATH"

if [ "$(id -u)" -ne 0 ]; then
    exec sudo -- "$0" "$@"
fi

rfkill unblock bluetooth
systemctl enable --now bluetooth

for _ in $(seq 10); do
    [ "$(cat /sys/class/rfkill/rfkill0/soft 2>/dev/null || echo 1)" = 0 ] && break
    sleep 1
done

bluetoothctl power on

echo "--- rfkill ---"
rfkill list bluetooth
echo "--- controller ---"
bluetoothctl show | grep -E 'Powered|PowerState|Discoverable|Pairable'
