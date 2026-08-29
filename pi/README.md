# pi/ — the voice satellite

Scripts that run on the Raspberry Pi that carries audio between the household and
Abbes. The Pi does nothing else: record, transcribe, ask the gateway, speak.

Everything here is committed and safe to publish. No hostnames, no IPs, no tokens —
those live in a gitignored `.env` on the Pi itself, modelled on `.env.example` at the
repository root.

## Layout

| Path | What it does |
|---|---|
| `bin/pi-recon.sh` | Prints host, audio devices, audio server, and Bluetooth state. Read-only. |
| `bin/bt-enable.sh` | Clears the Bluetooth rfkill block and powers the adapter on. Needs root; re-execs under `sudo`. |

## Running

Copy the tree to the Pi, or run over SSH from a checkout:

    ssh PI 'bash -s' < pi/bin/pi-recon.sh

`bt-enable.sh` needs a terminal for the sudo password:

    ssh -t PI 'bash -s' < pi/bin/bt-enable.sh

## Notes on this hardware

The adapter is an on-board BCM43430A1 on the UART. Its rfkill state is persisted by
`systemd-rfkill` in `/var/lib/systemd/rfkill/`, so an unblock survives reboot; BlueZ
then powers the controller on at boot via the default `AutoEnable=true`.

Bluetooth audio needs an audio server. Bare ALSA cannot carry A2DP — BlueZ alone
gives you a paired device and no sink.
