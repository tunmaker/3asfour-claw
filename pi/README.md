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
−30 dBFS at arm's length. Normalise before sending audio to whisper; a gain of roughly
x3.5 brought a real utterance to −3 dBFS.

**What survives a reboot, and what does not.** Verified by rebooting: the rfkill unblock
and the powered-on adapter come back on their own, and the WirePlumber drop-in keeps
working, so the bluez card reappears once a device connects. The *bond does not survive*.
This speaker stores no link key — its `info` file under `/var/lib/bluetooth` has no
`[LinkKey]` section — so after every boot it reports `Trusted: yes, Paired: no` and must
be paired again. `bt-pair.sh` clears the half-bond and re-pairs, and is safe to run on
every boot; the loop will need to call it before it can expect audio.

## Reaching the other two hosts

Verified from this Pi: the chat endpoint and the embedding endpoint answer over the LAN,
and a chat round-trip takes about 7s for a short reply.

The **gateway is not reachable from here**. It binds loopback on its own host by design
(see `docs/RUN.md` §7), so nothing on the LAN can POST to it. The Pi will need an SSH
tunnel to that host — the gateway itself must not be reconfigured to bind wider.
