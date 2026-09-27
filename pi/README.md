# pi/ — the voice satellite

The Raspberry Pi in the room. It listens for the name, records the request, sends
it to the orchestrator and plays the reply. Speech-to-text, the model and
text-to-speech all run elsewhere.

Everything here is committed and safe to publish. No hostnames, no IPs, no
tokens — the private values live in `~/.config/voicepi/voicepi.env` on the Pi.

## Layout

| Path | What it does |
|---|---|
| `bin/abbes-loop.py` | The loop, run as `abbes-loop.service` |
| `bin/abbes_wake.py`, `bin/abbes_match.py` | Wake-word detector (Vosk) and name matcher |
| `bin/abbes_audio.py` | The single shared microphone stream and its pre-roll buffer |
| `bin/abbes_stream.py` | Sends a recording to the orchestrator and plays the streamed reply |
| `bin/abbes_config.py` | Reads `voicepi.env` for every script |
| `bin/vosk-install.sh` | Installs Vosk in a venv and downloads the wake-word model |
| `bin/audio-stack-install.sh`, `bin/abbes-audio-setup.sh` | PipeWire for a headless host; sink and volume at boot |
| `bin/abbes-audio-unwedge.sh` | Rebinds the USB controller (see the hardware notes) |
| `bin/mic-level.sh`, `bin/wake-listen.sh`, `bin/wake-tally.sh` | Debugging: live levels, the detector alone, trigger counts |
| `wake-decoys.txt` | Competing words for the wake grammar. Install to `~/.config/voicepi/` |
| `systemd/` | `abbes-loop`, `abbes-audio`, and `openclaw-tunnel` (the SSH tunnel to the gateway host) |

## Running

Copy the scripts together; the loop imports its siblings:

    scp pi/bin/*.py pi/bin/*.sh PI:bin/
    scp pi/wake-decoys.txt PI:.config/voicepi/
    ssh PI systemctl --user restart abbes-loop

Logs: `journalctl --user-unit=abbes-loop -f` (see *Debugging* for why not `--user -u`).

## The loop

    name heard -> tone -> record until silence -> orchestrator -> play each sentence as it arrives

- **The tone means "listening".** Start talking within `VAD_START_SECS` (8 s).
  Recording stops after `VAD_SILENCE_SECS` of quiet, or at `VAD_MAX_SECS`.
- **One breath works too.** The second of audio before the trigger is kept, so
  "Abbes, add milk" is not clipped; the orchestrator strips the name.
- **Follow-ups need no name** for `WAKE_FOLLOWUP_SECS` (8 s) after a reply.
  Anything said in that window is a request, so keep it short in a noisy room.
- **Failure is a low two-note tone** — the orchestrator was unreachable, or the
  agent produced nothing. Silence after the listening tone means nothing was heard.
- **Manual trigger:** `echo go > $XDG_RUNTIME_DIR/abbes-trigger`. `--once` runs a
  single turn in the foreground.
- **Recordings never persist.** The clip is deleted in a `finally`, and startup
  sweeps any left behind.

Each turn logs what whisper heard, the reply, and the timings:

    HEARD: 'what is on my shopping list?'
    REPLY: '...'  stt 1063ms first-audio 4899ms total 11782ms

## Notes on this hardware

**Input and output are one USB speakerphone** — a Jabra SPEAK 510. That single fact
removes most of what used to be in this section, so the history is kept below rather
than the workarounds.

**It cancels its own output in hardware, and that is load-bearing.** Measured 11 Sep
2026: a 440 Hz tone at 70% volume, played out of this speaker and recorded on its own
microphone at the same instant, peaks at **−48.9 dBFS** — below the room's own quiet
floor of −45.7. The microphone cannot hear the speaker at all. So the microphone is
never muted, `WAKE_MUTE_TAIL_SECS` is gone, the acknowledgement tone can play into a
live microphone without landing in the recording, and **you can interrupt Abbes
mid-sentence**. If this device is ever swapped for a separate speaker and microphone,
muting the microphone during playback has to come back.

**Its microphone is quiet and it is 16 kHz native.** Floor −45.7 dBFS median (−51.9
min, −31.0 peak) against speech around −20. The webcam microphone it replaced floored
at **−30.1** — at, or above, every threshold that was meant to sit over it, which is
why the wake gate ran the decoder on room noise continuously and why the VAD could
barely tell a talking person from an empty room. With 18 dB of headroom a fixed
threshold is enough: `VAD_THRESHOLD_DBFS=-36`, `WAKE_GATE_DBFS=-40`, no adaptation.
It also delivers exactly the 16 kHz mono the recogniser wants, so nothing is resampled.

Re-measure both numbers if the device or the room changes — `bin/mic-level.sh`, and the
echo test is worth repeating on any new speakerphone:

```bash
parecord --device=$MIC --rate=16000 --channels=1 --format=s16le --file-format=wav /tmp/e.wav &
paplay --device=$SINK /tmp/tone.wav       # anything loud
```

If the recording during playback sits near the room floor, the cancellation is real.
If it sits 20 dB above it, the microphone hears the speaker and muting has to come back.

**The USB controller is the real constraint on this Pi, and it is shared.**
Everything hangs off one `dwc_otg` controller behind one SMSC9514 hub — the
network included:

```
dwc_otg root hub (480M)
 └── SMSC9514 hub
      ├── Dev 003  Ethernet   480M   smsc95xx
      ├── Dev 004  USB Wi-Fi  480M   rtw88_8821au
      └── Dev 005  Jabra       12M   snd-usb-audio   <- full speed
```

The speakerphone is a **full-speed (12M) device behind a high-speed hub**, so
every audio frame is a USB *split transaction*, and split isochronous transfers
are the known weak point of `dwc_otg`'s FIQ. Anything else moving data across
that hub competes for the same scheduling: the webcam did while it was fitted,
and the Wi-Fi adapter does now. A few NYET entries an hour is the bus
complaining without losing the stream — `pw-top` still shows the capture node
`R`unning with `ERR 0`. Hundreds of them, with capture stopping, is the wedge
described below.

It wedged, once, and the shape is worth knowing because nothing about it looks
like an audio fault:

- 530 kernel errors, every one of them on the speakerphone's audio-in endpoint:
  `Transfer to device 4 endpoint 0x3 failed - FIQ reported NYET. Data may have
  been lost.` Nothing else on the bus, ever.
- Then capture simply stopped. ALSA still reported the stream `Running`,
  PipeWire still listed the source `RUNNING`, the device was still enumerated,
  and `parecord` produced a **44-byte WAV — a header and no samples**.
- **The webcam's own microphone was equally dead**, while Ethernet on the same
  hub kept working. So it is not the device: it is isochronous scheduling for
  every audio device at once.
- A `USBDEVFS_RESET` of the speakerphone did not recover it. Neither did the
  same reset with nothing holding the device. Only a reboot did.

**Restarting is
not a repair**: a fresh `parecord` on a wedged endpoint is exactly as deaf as
the old one, which is why the loop backs off to five minutes instead of
restarting every 38 seconds. It ran 404 times in four hours once, recovering
nothing and holding the bus down while it tried.

If the assistant goes silent and `journalctl -k | grep NYET` has entries, the
controller is wedged and it needs a reboot. Check it before suspecting the
microphone. `abbes-audio-unwedge.sh` rebinds the controller, which clears the
stuck FIQ channel where a device-level USB reset cannot.

**`dwc_otg.fiq_fsm_mask=0xD` was tried and reverted. Do not try it again.**
The reasoning was sound: bit 1 governs periodic splits, which is what a
full-speed audio device behind a high-speed hub actually uses, so clearing it
moves those transfers off the FIQ onto the plain IRQ handler. It did exactly
what it promised on the capture side — zero NYET errors, microphone solid.

It destroyed playback. Measured by playing a 3s 440 Hz tone out the speakerphone
and recording it on the webcam's microphone, which is a separate device with no
echo-cancellation relationship to it:

| | envelope of a steady tone |
|---|---|
| default `0xF` | flat |
| `0xD` | **27 dB swing** (-9 to -36 dBFS), audible as stutter |

Confirmed as the parameter and not bus contention: with the loop stopped and the
camera not polling at all, the same test still showed a 19 dB swing. The mask
cannot separate isochronous from interrupt splits — bit 1 is both — so there is
no middle setting that keeps capture fixed without breaking playback this way.

The remaining untried option is `dwc_otg.speed=1`, which forces the whole
controller to full speed so that no split transactions exist at all. That
genuinely eliminates the failure class, at the cost of putting Ethernet on a
shared 12 Mbit bus. It is a diagnostic setting, not a deployment one.

The honest conclusion is that this speakerphone on a Pi 3B is marginal by
construction. A Pi 4 or 5 has a real xHCI controller and none of this applies.


**Earlier arrangements, for anyone tempted to go back.** Before the speakerphone,
output was the 3.5mm jack and input was the webcam across the room. Before that it was
Bluetooth: the speaker had only ever paired as a *headset*, its cached record listing
the Headset UUID alone, so PipeWire gave it `headset-head-unit` — mono 8 kHz CVSD,
telephone quality — and `a2dp-sink` was never offered. Getting A2DP needed a re-pair,
the re-pair needed the speaker in pairing mode, and the adapter wedged partway through
(`hci0 DOWN`, `Connection timed out`). If Bluetooth is ever wanted again, pair it while
it advertises A2DP and check `pactl list cards` actually offers `a2dp-sink` before
believing it works.

## Reaching the gateway host

The gateway and the orchestrator both bind loopback on their host by design, so
nothing on the LAN can POST to them. `openclaw-tunnel.service` forwards both ports
over SSH and restarts on failure. A dead tunnel is indistinguishable from a dead
orchestrator at the HTTP layer; either way the loop plays the failure tone.

## The wake word

Say **Abbes**. The detector uses a Tunisian Vosk model because it recognises the
name reliably; it is used for nothing else, and everything after the trigger is English. Detection runs entirely on the Pi with
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

## Boot

`abbes-audio.service` runs before the loop: it waits for PipeWire, selects the analog
sink, routes the card to the jack rather than HDMI, and pins the volume to
`SPEAKER_BOOT_VOLUME`. `abbes-loop.service` only `Wants` it, so the loop still starts if
audio setup fails — a silent assistant that hears you is better than none at all.

Volume is pinned rather than left alone because it drifts otherwise, and an unpinned
level silently leaves Abbes too quiet to hear.

**Quote any config value containing spaces.** `voicepi.env` is read both by the Python
loop and sourced by shell scripts. An unquoted `WAKE_WORDS` makes bash try to execute
the word list as a command. The loop strips surrounding quotes when it parses the
file, so quoting is safe for both readers.
