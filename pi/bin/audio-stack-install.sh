#!/usr/bin/env bash
set -euo pipefail

PATH="/usr/sbin:/sbin:$PATH"
export DEBIAN_FRONTEND=noninteractive

PACKAGES=(
    pipewire
    pipewire-audio
    pipewire-pulse
    wireplumber
    pulseaudio-utils
)

sudo -n apt-get update -qq
sudo -n apt-get install -y -qq "${PACKAGES[@]}"

sudo -n loginctl enable-linger "$USER"

mkdir -p ~/.config/wireplumber/wireplumber.conf.d

# Streaming TTS pushes one sentence at a time. Letting the sink suspend in the
# gaps costs a wake-up on every sentence, audible as a click at each boundary.
# This mattered enormously over Bluetooth and still matters a little over the
# jack, and it costs nothing to keep the output awake on a machine whose only
# job is to speak.
cat > ~/.config/wireplumber/wireplumber.conf.d/51-alsa-no-suspend.conf <<'CONF'
monitor.alsa.rules = [
  {
    matches = [
      { node.name = "~alsa_output.*" }
    ]
    actions = {
      update-props = {
        session.suspend-timeout-seconds = 0
      }
    }
  }
]
CONF

# Any BlueZ configuration from when the speaker was wireless. Left behind it
# would keep re-adding a device we deliberately stopped using.
rm -f ~/.config/wireplumber/wireplumber.conf.d/50-headless-bluez.conf \
      ~/.config/wireplumber/wireplumber.conf.d/51-bluez-no-suspend.conf

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
