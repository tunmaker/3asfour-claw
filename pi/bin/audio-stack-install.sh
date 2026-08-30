#!/usr/bin/env bash
set -euo pipefail

PATH="/usr/sbin:/sbin:$PATH"
export DEBIAN_FRONTEND=noninteractive

PACKAGES=(
    pipewire
    pipewire-audio
    pipewire-pulse
    wireplumber
    libspa-0.2-bluetooth
    pulseaudio-utils
)

sudo -n apt-get update -qq
sudo -n apt-get install -y -qq "${PACKAGES[@]}"

sudo -n loginctl enable-linger "$USER"

# WirePlumber gates the BlueZ monitor on being the active seat; SSH sessions have none.
mkdir -p ~/.config/wireplumber/wireplumber.conf.d
cat > ~/.config/wireplumber/wireplumber.conf.d/50-headless-bluez.conf <<'CONF'
wireplumber.profiles = {
  main = {
    monitor.bluez.seat-monitoring = disabled
  }
}
CONF

# Streaming TTS pushes one sentence at a time. Letting the sink suspend in the gaps
# pays the A2DP wake-up on every sentence, which is audible as a stutter.
cat > ~/.config/wireplumber/wireplumber.conf.d/51-bluez-no-suspend.conf <<'CONF'
monitor.bluez.rules = [
  {
    matches = [
      { node.name = "~bluez_output.*" }
    ]
    actions = {
      update-props = {
        session.suspend-timeout-seconds = 0
      }
    }
  }
]
CONF

systemctl --user daemon-reload
systemctl --user enable --now pipewire.socket pipewire-pulse.socket wireplumber.service
systemctl --user restart wireplumber.service

for _ in $(seq 15); do
    pactl info >/dev/null 2>&1 && break
    sleep 1
done

echo "--- server ---"
pactl info | grep -E 'Server Name|Default Sink|Default Source'
echo "--- cards ---"
pactl list cards short
