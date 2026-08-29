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

## Phase 0 status

Both round-trips now work from this Pi.

The **speech-to-text host is an LXC container**, which is what made its failure hard to
read from inside: `/proc/meminfo` is lxcfs-filtered, so it reports the container's memory
*limit* as if it were physical RAM, and `journalctl -k` and `dmesg` are empty because a
container has no kernel log of its own. An out-of-memory kill there is the container's
cgroup limit being enforced by the LXC host, and the report lands in the *host's* kernel
log, not the container's. Adding a user to `adm` or `systemd-journal` inside the container
cannot surface it. Raising the container's swap fixed the kills.

The **gateway is reached over an SSH tunnel** (`openclaw-tunnel.service`), because it
binds loopback on its own host by design. The tunnel restarts on failure and starts at
boot. Note that a dead tunnel is indistinguishable from a dead gateway at the HTTP layer,
so the loop's failure path must cover both.

**Transcription quality over the Bluetooth mic is not usable.** The HFP link is 8kHz CVSD.
Recorded speech plays back intelligibly to a human, but whisper medium returns
hallucinations from it — including a repeat-loop on `language=auto`. This is the narrowband
channel, not the model: a headset profile cannot do better than 8kHz. A USB microphone at
16kHz is the fix; treat the Bluetooth mic as a fallback for playback-only use.

## Phase 1 — Piper latency on a Pi 3B

Installed via `bin/piper-install.sh` to `~/piper` (~292MB with three voices). Note the
Debian package named `piper` is a gaming-mouse configurator, not this; and upstream moved
from `rhasspy/piper` to `OHF-Voice/piper1-gpl` in late 2025.

Measured on this Pi, short sentences, steady state:

| Voice | Wall per sentence | RTF |
|---|---|---|
| `ar_JO-kareem-medium` | ~9.6s | ~4.2 |
| `ar_JO-kareem-low` | ~9.3s | ~4.5 |
| `fr_FR-siwis-medium` | ~5.5s | ~1.6 |
| `en_US-lessac-medium` | ~5.1s | ~1.7 |

**Arabic synthesis runs at roughly 4x slower than real time.** Three things this rules
out: it is not model-load overhead (measured by piping several sentences through one
process — the gaps between outputs stay at ~9.4s); it is not voice quality (`low` is
within 3% of `medium`); and it is not thread count (`OMP_NUM_THREADS=1` and `4` differ by
under 2%). The Cortex-A53 is simply the limit.

Budget roughly 10s of speech synthesis per reply on top of transcription and the model's
own answer. Anything conversational needs either a faster host for TTS or much shorter
replies.

## Phase 2 — the loop

`bin/abbes-loop.py`, run as `abbes-loop.service`. It blocks on a FIFO, so a turn is
started by writing to it — `bin/abbes-trigger.sh`, or `echo go > $XDG_RUNTIME_DIR/abbes-trigger`.
A GPIO button later only has to write to the same FIFO. `--once` runs a single turn in the
foreground, which is how to debug it.

    trigger -> record until silence -> whisper -> gateway -> pick voice -> synthesise -> play

**Recordings never persist.** The clip is deleted in a `finally`, so it goes whether
transcription succeeded, failed, or threw. Verified: no `/tmp/abbes-*.wav` survives a turn.

**Turn log** is `~/.local/state/voicepi/turns.jsonl`, mode 600, pruned to the last 2 hours
on every write. It lives outside any repository rather than merely being gitignored.

**Failure path.** Any unreachable or timed-out dependency speaks `ما نجمش نجاوبك توة` and
returns to idle. That phrase is pre-rendered to `~/.cache/voicepi/failure.wav` at startup,
because synthesising it locally costs ~13s — far too slow to sit inside a failure path.
It needs no model and no network.

**Text to speech is remote-first with a local fallback.** `PIPER_URL` is tried first; if it
is unset or unreachable the loop falls back to local Piper and says so in the log. The loop
therefore works before, during and after the inference host gains a Piper service.

**VAD is a level threshold, and it must be tuned per microphone.** With the webcam mic the
room floor measured −35 dBFS and speech about −25 dBFS, so `VAD_THRESHOLD_DBFS=-30` sits
between them. The default of −45 never detected silence at all and every turn ran to
`VAD_MAX_SECS`. Re-measure after changing microphones: record a few seconds of silence and
put the threshold above the floor.

## Talking to the gateway

The supported interface is the `openclaw agent` CLI, run on the gateway host over SSH as
the user that owns `~/.openclaw`. The Pi never formats a shell command containing the
transcript: the key carries a **forced command**, `gateway/abbes-ask`, which reads the
message from stdin and passes it via `--message-file`. Whisper output is untrusted text
arriving from a microphone and will contain quotes, newlines and Arabic script, so keeping
it off the command line is deliberate.

Install `gateway/abbes-ask` as `/usr/local/bin/abbes-ask` on the gateway host and restrict
the key in `authorized_keys`:

    restrict,command="/usr/local/bin/abbes-ask" ssh-ed25519 AAAA... voicepi-openclaw-tunnel

Note the tunnel key needs `port-forwarding` as well; use a **second key** for the agent
call rather than widening the tunnel key, so a forced command and a port forward never
share one credential.

The wrapper asks for `--json` and reads `final` from the envelope, checking `status` is
`ok` — `error` and `timeout` are distinct statuses and both must fail loudly rather than
returning empty text that would be synthesised as silence.

**Turns are never retried.** A gateway timeout can still complete server-side, so a retry
could run the turn twice — which matters as soon as tools write to the grocery list or the
baby log. On failure the loop speaks the degradation phrase and returns to idle.

A stable `--session-key voice` keeps conversational context across turns; with
`--agent main` it scopes to `agent:main:voice`.

## Text to speech, remote

`PIPER_URL` points at the Piper server on the inference host (port 9091, no auth, JSON in,
WAV bytes out). Measured from this Pi:

| Voice | Audio | Wall | RTF |
|---|---|---|---|
| `ar_JO-kareem-medium` | 3.84s | **0.21s** | 0.056 |
| `fr_FR-siwis-medium` | 1.65s | 0.08s | 0.049 |
| `en_US-lessac-medium` | 1.38s | 0.07s | 0.048 |

About 45x faster than local Piper, which took ~9.6s for ~2.3s of Arabic.

**Local Piper is kept deliberately**, against the server's handoff advice to delete it. It
is the fallback when the LAN or the inference host is down, and it is what renders the
degradation phrase — which must work with no network and no model at all. It costs ~292MB
of disk on a 29GB card.

`PIPER_TIMEOUT` is 5s, not the 30s the handoff suggests. A closed port on a *live* host
drops packets instead of refusing them, so the full timeout is spent before falling back:
at 30s a single failed turn took 41s end to end. Synthesis itself is 0.2s, so 5s is still
25x headroom.

Voice names must match exactly — an unknown voice returns the default **with HTTP 200**,
so a typo silently reads French in an Arabic voice rather than erroring.

## Whisper noise labels

Whisper annotates non-speech rather than returning nothing: `(موسيقى)`, `(مسجد)`, `(مشي)`,
`[Music]`, `[Silence]`, `*soupir*`. On a quiet or short clip the whole transcript can be one
of these, and on a normal turn one usually precedes the speech. They were reaching the
agent as part of the prompt.

`clean_transcript` drops lines that consist *only* of such an annotation. Parentheses
inside real speech are left alone — only a whole-line label is removed. If nothing
survives, the turn is treated as silence and the loop returns to idle without calling the
agent.
