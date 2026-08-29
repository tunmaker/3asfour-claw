# pi/ — the voice satellite

Scripts that run on the Raspberry Pi that carries audio between the household and
Abbes. The Pi does nothing else: record, transcribe, ask the gateway, speak.

Everything here is committed and safe to publish. No hostnames, no IPs, no MAC
addresses, no tokens — the speaker's address is passed as an argument or via
`BT_SPEAKER_MAC` in a gitignored `.env` on the Pi.

## Layout

| Path | What it does |
|---|---|
| `bin/pi-recon.sh` | Prints host, audio devices, audio server, and Bluetooth state. Read-only. |
| `bin/bt-enable.sh` | Clears the Bluetooth rfkill block and powers the adapter on. Needs root. |
| `bin/audio-stack-install.sh` | Installs PipeWire + WirePlumber + the BlueZ SPA plugin and configures them for a headless host. |
| `bin/bt-pair.sh` | Pairs, trusts, and connects a Bluetooth audio device. Takes a MAC. |
| `bin/bt-audio-test.sh` | Plays a tone over A2DP, then records over HFP and reports levels. Takes a MAC. |

## Running

Run over SSH from a checkout:

    ssh PI 'bash -s' < pi/bin/pi-recon.sh
    ssh PI 'bash -s' < pi/bin/audio-stack-install.sh
    ssh PI 'bash -s AA:BB:CC:DD:EE:FF' < pi/bin/bt-pair.sh

## Notes on this hardware

**Adapter.** On-board BCM43430A1 on the UART. Its rfkill state is persisted by
`systemd-rfkill` in `/var/lib/systemd/rfkill/`, so one unblock survives reboot; BlueZ
then powers the controller on at boot via the default `AutoEnable=true`.

**The headless BlueZ trap.** WirePlumber's `main` profile gates its BlueZ monitor on
`monitor.bluez.seat-monitoring`, which only fires for a session on the active seat. An
SSH session has no seat, so the monitor never loads, no A2DP endpoint is registered
with BlueZ, and `connect` fails with `br-connection-profile-unavailable` — after which
some speakers silently drop the bond. The drop-in in `audio-stack-install.sh` disables
seat monitoring and fixes both symptoms. If Bluetooth audio ever goes missing after a
reinstall, check that file first.

**Profiles are exclusive.** A headset gives you `a2dp-sink` (stereo 48kHz playback, no
mic) *or* `headset-head-unit` (mono 8kHz CVSD, playback **and** mic) — never both. The
loop must either sit in the headset profile throughout, or switch per turn and pay the
profile-change delay.

**Mic level is low.** Expect a noise floor around −49 dBFS and normal speech well under
−30 dBFS at arm's length. Normalise before sending audio to whisper.
