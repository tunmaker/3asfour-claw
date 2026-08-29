#!/usr/bin/env bash
set -uo pipefail

PATH="/usr/sbin:/sbin:$PATH"

section() { printf '\n=== %s ===\n' "$1"; }

section "host"
uname -srm
grep -E '^(PRETTY_NAME|VERSION_CODENAME)' /etc/os-release

section "resources"
free -h
df -h / | tail -1

section "playback devices"
aplay -l 2>&1

section "capture devices"
arecord -l 2>&1

section "audio server"
systemctl --user is-active pipewire wireplumber pulseaudio 2>&1
dpkg -l 2>/dev/null | awk '/pipewire|wireplumber|pulseaudio|bluez|bluealsa/ {print $2, $3}'

section "bluetooth"
systemctl is-enabled bluetooth
systemctl is-active bluetooth
rfkill list bluetooth 2>&1
bluetoothctl show 2>&1 | grep -E 'Controller|Powered|PowerState|Discoverable'
bluetoothctl devices 2>&1
