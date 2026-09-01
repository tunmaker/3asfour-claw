# pi/ — the voice satellite

Scripts that run on the Raspberry Pi that carries audio between the household and
Abbes. The Pi does nothing else: record, transcribe, ask the gateway, speak.

Everything here is committed and safe to publish. No hostnames, no IPs, no
tokens — the private values live in a gitignored `.env` on the Pi.

## Layout

| Path | What it does |
|---|---|
| `bin/pi-recon.sh` | Prints host, audio devices, audio server, and output routing. Read-only. |
| `bin/audio-stack-install.sh` | Installs PipeWire + WirePlumber and configures them for a headless host. |
| `bin/abbes-camera-reset.sh` | Unwedges the USB webcam. See the camera note below. |
| `bin/vosk-install.sh` | Installs Vosk in a venv and downloads one small offline model. |
| `bin/abbes_wake.py` | Wake-word detector. Importable, and runnable standalone with `--listen`. |
| `bin/abbes_audio.py` | The single shared microphone stream, its pre-roll ring buffer, and level metering. |
| `bin/abbes_config.py` | Reads `~/.config/voicepi/voicepi.env` for every script. |
| `bin/wake-listen.sh` | Runs the detector on its own for debugging. |
| `bin/wake-tally.sh` | Summarises recorded trigger times, for judging false positives. |
| `wake-decoys.txt` | Competing words for the wake grammar. Install to `~/.config/voicepi/`. |
| `bin/abbes-volume` | Speaker volume, as an SSH forced command. Install to `/usr/local/bin`. |
| `bin/mic-level.sh` | Live microphone meter, for setting the VAD and gate thresholds. |

## Running

Run over SSH from a checkout:

    ssh PI 'bash -s' < pi/bin/pi-recon.sh
    ssh PI 'bash -s' < pi/bin/audio-stack-install.sh

The loop is no longer a single file — `abbes-loop.py` imports `abbes_wake`,
`abbes_audio` and `abbes_config` from the same directory — so copy them together
rather than piping one over stdin:

    scp pi/bin/*.py pi/bin/*.sh PI:bin/
    scp pi/wake-decoys.txt PI:.config/voicepi/

## Notes on this hardware

**Output is the 3.5mm jack**, wired to the speaker's aux input. It was Bluetooth, and
that is worth recording because the failure was not obvious.

The speaker had only ever paired as a *headset*: its cached record listed the Headset
UUID and nothing else, so PipeWire gave it `headset-head-unit` and `a2dp-sink` was never
offered. That profile is mono 8kHz CVSD — telephone quality — which is why spoken
replies were faint and muffled, and why a stray Bluetooth microphone kept appearing
alongside. Getting A2DP needed a re-pair; the re-pair needed the speaker in pairing
mode; and the adapter wedged partway through (`hci0 DOWN`, `Can't init device hci0:
Connection timed out`, `Failed to set mode: Authentication Failed`). A cable has none
of these states.

What the cable removes, beyond the noise: a device that renegotiates its profile on
every reconnect, a sink whose name changes with it, WirePlumber auto-switching to the
headset profile whenever anything opens a microphone, a speaker that restores its own
saved volume behind us, and a bond that did not survive a reboot because this speaker
stores no link key.

If Bluetooth is ever wanted again, the thing to get right is the pairing: pair it while
it advertises A2DP, and check `pactl list cards` offers `a2dp-sink` before believing it
works. `headset-head-unit` as the only option means it paired as a headset.

**Mic level is low, and it moves.** The same microphone at the same gain measured a
−24.8 dBFS noise floor at 3am and −36.3 at 4pm. A fixed threshold is therefore wrong
twice a day: one set for the quiet hours left the assistant completely deaf in the
afternoon, with 0 of 39 windows crossing it. The gate now tracks the floor — see
`abbes_wake.Listener` and `abbes_wake_test.py`. Do not replace it with a constant.

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

**Transcription quality over a Bluetooth mic is not usable.** The HFP link is 8kHz CVSD.
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

`bin/abbes-loop.py`, run as `abbes-loop.service`. A turn starts when the wake word is
heard, or when anything writes to the FIFO — `bin/abbes-trigger.sh`, or
`echo go > $XDG_RUNTIME_DIR/abbes-trigger`. A GPIO button later only has to write to the
same FIFO. `--once` runs a single turn in the foreground, which is how to debug it.

    name heard -> tone -> record until silence -> whisper -> gateway -> pick voice -> synthesise -> play

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

## The wake word

Say **يا عباس** or **عباس**. Detection runs entirely on the Pi with
[Vosk](https://alphacephei.com/vosk/): no audio, and no text derived from audio, leaves
this host until the name has actually been recognised here.

Install with `bin/vosk-install.sh`, then copy `wake-decoys.txt` to `~/.config/voicepi/`
and set the `WAKE_*` keys. The loop is stdlib-only, so it re-execs itself under
`WAKE_VOSK_PYTHON` to reach Vosk; if Vosk is missing it logs a warning and falls back to
the FIFO trigger, and everything else still works.

### The model

`vosk-model-small-ar-tn-0.1-linto` — Tunisian Arabic, from Linagora, Apache 2.0.
158 MB compressed, 267 MB unpacked, and it holds **375 MB of anonymous RSS** once loaded.
That is the whole reason the design looks the way it does on a 905 MB Pi.

It was chosen over the alternatives on measurement, not preference:

| Model | Recall | False fires | RTF | Verdict |
|---|---|---|---|---|
| Tunisian small, grammar of just the name | 5/6 | **12/12** | 0.8 | Useless: the decoder had nothing else to choose from |
| Tunisian small, free transcription | 4/6 | 0/12 | **3.3** | Accurate, three times too slow |
| French small (41 MB), free transcription | **1/6** | 0/18 | 5.0 | The phonetic-approximation fallback. Worse on both counts |
| **Tunisian small, grammar + decoys** | **5/6** | **0/18** | 1.0 | What ships |

### Why there is a decoy list

Vosk decodes into the smallest set of words it is given. Restricted to the name alone it
has no alternative hypothesis, so *every* sentence in the room decodes to the name — that
is the 12/12 row above, and it is the single most surprising thing about this setup.
`wake-decoys.txt` gives it somewhere else to go: about 130 common Derja words, family
names, and words that sound like عباس (عبد، عباد، باس، راس). Words outside the model's
vocabulary are dropped silently at load.

**This is where "يا" is handled.** The vocative particle precedes every name in Derja, so
it is a decoy, never a trigger. The grammar contains the full name; "يا" on its own can
only ever decode to the decoy.

### Why there is an energy gate

The acoustic model costs about **one second of CPU per second of audio** on a Pi 3B, and
that floor does not move: sweeping `--beam` from 11 to 7 and `--max-active` from 7000 to
600 changed RTF by less than 0.05, because the cost is the neural forward pass, not the
graph search. BLAS is statically linked into `libvosk.so`, so thread count is fixed too.

So the decoder only runs when the room is above `WAKE_GATE_DBFS`. Idle cost measured
**2.3% of one core** in a quiet room. During continuous speech it runs at roughly real
time and leans on the stream's backlog buffer, which absorbs about 70 seconds of unbroken
talking before it has to drop audio.

Closing the gate does not reset the recogniser. A pause between "يا" and "عباس" is normal
speech, and resetting there throws away the first half of the name — that mistake cost
recall of 1/5 until it was fixed. State is discarded only after `WAKE_GATE_IDLE_RESET_SECS`
of continuous quiet.

### Tuning

| Key | Meaning |
|---|---|
| `WAKE_WORDS` | What the recogniser may hear. Must exist in the model's vocabulary. |
| `WAKE_CANDIDATES` | What counts as the name, compared after normalisation. |
| `WAKE_FUZZ` | Edits allowed against each candidate. 0 strict, 1 default, 2 twitchy. |
| `WAKE_GATE_DBFS` | Below this the decoder sleeps. Put it above the room's noise floor. |
| `WAKE_PREROLL_SECS` | Audio kept from before the trigger. |
| `WAKE_FOLLOWUP_SECS` | Window after a reply where the name is not needed. 0 disables. |
| `WAKE_MUTE_TAIL_SECS` | How long the mic stays muted after playback. |

Comparison folds diacritics, alef forms (أإآ→ا, ى→ي, ة→ه) and Latin accents, then allows
`WAKE_FUZZ` edits, so عبّاس, عباس, Abbes and abbas all match one entry.

To change the name: put the new word in both `WAKE_WORDS` and `WAKE_CANDIDATES`, confirm
it exists in `<model>/graph/words.txt`, and add the old name to `wake-decoys.txt`.

**If it fires on other names, lengthen the phrase rather than fighting the model.** Put
only `"يا عباس"` in `WAKE_WORDS`; two words in sequence are far harder to hit by accident.

### Debugging

    systemctl --user stop abbes-loop     # it holds the microphone
    bin/wake-listen.sh                   # prints one line per trigger, nothing else
    bin/wake-tally.sh                    # counts triggers per hour

`wake-listen.sh` deliberately prints **only** the matched trigger. There is no flag to dump
what it heard otherwise, because such a flag left on would be a transcript of the room.
The tally file holds timestamps and nothing else, for the same reason.

Loop output goes to the system journal, not the user journal:

    journalctl --user-unit=abbes-loop -f

`--user-unit=` and `--user -u` are not the same thing, and the difference bites here.
`--user` restricts the search to a per-user journal namespace, which this Pi does not
have — journald is volatile and does not split files per UID — so `journalctl --user -u
abbes-loop` answers **"No journal files were found"** even while `systemctl --user status`
is printing those very lines. `--user-unit=` reads the system journal and filters by unit,
which is what is wanted. No sudo, and no grepping every service on the box.

The same is not true of the gateway and inference hosts, where `--user -u` works. This is
a property of this Pi's journald, not of user units in general.

### Not hearing yourself

The microphone is hard-muted for the whole turn after recording ends: chunks are dropped
at the source and the recogniser is reset. `WAKE_MUTE_TAIL_SECS` then keeps it muted past
the end of playback, covering output latency and the room's own reverb tail.

That tail is what matters. At 0.7s a follow-up window recorded the last word of Abbes's
own reply and sent it back to the gateway; 1.5s fixed it. `play()` additionally waits out
the file's real duration, which measurement later showed is redundant — `pw-play` already
blocks for the full length (7.3s for a 7.2s file), cold sink or warm. It is kept as a cheap
guard against a player that does not.

Verified: asked to say its own name, Abbes answered `...وسمّيتني "عباس" قبيلة...` through
the speaker, did not wake itself, and the follow-up window stayed silent.

### Known limits

- Recall on the **bare name alone** is weaker than on "يا عباس" followed by a request.
  A short isolated word gives the decoder little to work with.
- All figures above are from synthetic speech played through the speaker and
  re-recorded — a harsher path than a person talking to the microphone, and not a
  substitute for a real tuning session.
- The 375 MB model leaves roughly 350 MB free. Nothing else should move onto this Pi.

## Speech to text — and why the audio is sent untouched

`WHISPER_URL` points at the **Vosk `ar-tn` endpoint**, not whisper. Both accept the
identical multipart POST and return `{"text": ...}`, so switching engines is a port
change and nothing else. Whisper keeps resolving Derja toward MSA and fragments when it
cannot; the Vosk model is trained on TARIC, real Tunisian speech.

**Do not apply makeup gain.** `AUDIO_NORMALIZE` defaults to `0` and should stay there.
The loop used to normalise every clip to −24 dBFS RMS, which was tuned for whisper and
actively broke Derja recognition:

| | with gain (x2.72) | without |
|---|---|---|
| 6s of "قداش الوقت" | `صافية` | `قداش الوقت` |

A real recording measured rms −31.6 dBFS but **peak −9.3 dBFS**; multiplying by 2.72 put
the peaks within a decibel of clipping. The Vosk endpoint is level-insensitive across
about 25dB, so the gain bought nothing and cost the transcript. Measure the level instead
— it is printed on every turn:

    recorded 6.1s, rms -31.6 dBFS, peak -9.3 dBFS

Use `bin/mic-level.sh` to see the same figures live when setting thresholds. It must be
run directly on the Pi, in a terminal you are watching — a level meter driven over a
non-interactive SSH command prints its cue only after the recording window has closed,
which invalidates the measurement.

## Speaker volume

`bin/abbes-volume`, installed to `/usr/local/bin/abbes-volume`, reads and sets the volume
of `SPEAKER_SINK`. It exists so Abbes can be told out loud to be quieter, and it is reached
from the gateway host over SSH:

    restrict,command="/usr/local/bin/abbes-volume" ssh-ed25519 AAAA... openclaw-speaker

That entry is the whole of what the gateway can do on this Pi. The key gets no shell, no
pty and no forwarding, and the script matches every argument against a fixed pattern before
it reaches `pactl` — `set "99; rm -rf /"` is rejected, not escaped.

    abbes-volume get | up | down | set <0-100> | mute | unmute

`VOLUME_STEP` (default 10) and `VOLUME_MAX` (default 100) are read from `voicepi.env`.
`XDG_RUNTIME_DIR` is set explicitly because a non-login SSH session does not get one, and
without it `pactl` cannot find the user's PipeWire socket.

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

## Boot

`abbes-audio.service` runs before the loop: it waits for PipeWire, selects the analog
sink, routes the card to the jack rather than HDMI, and pins the volume to
`SPEAKER_BOOT_VOLUME`. `abbes-loop.service` only `Wants` it, so the loop still starts if
audio setup fails — a silent assistant that hears you is better than none at all.

Volume is pinned rather than left alone because it drifts otherwise, and an unpinned
level silently leaves Abbes too quiet to hear.

**Quote any config value containing spaces.** `voicepi.env` is read both by the Python
loop and sourced by shell scripts. An unquoted `WHISPER_PROMPT` made bash try to execute
the vocabulary list as a command. The loop strips surrounding quotes when it parses the
file, so quoting is safe for both readers.
