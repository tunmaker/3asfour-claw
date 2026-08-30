# orchestrator/ — the streaming voice path

Phase 1 of the streaming migration: proving the gateway's WebSocket control plane
can carry a voice turn, before anything is rewritten to depend on it.

Nothing here is wired into the running assistant yet. Both scripts are read-mostly
probes, run by hand on the gateway host.

| File | What it does |
| --- | --- |
| `abbes-orchestrator.mjs` | The service. WAV in, speech out. `/turn`, `/turn/stream`, `/health`. |
| `gateway-client.mjs` | Persistent operator connection: connect, subscribe, send a turn, stream deltas. |
| `sentences.mjs` | Cuts a token stream into speakable pieces. Arabic-aware. |
| `sentences.test.mjs` | 23 assertions over that. `node sentences.test.mjs`. |
| `gw-probe.mjs` | Prints what this gateway build advertises. Read-only. |
| `gw-stream.mjs` | One turn, verifying deltas reconstruct the final message. |

Both read `OPENCLAW_GATEWAY_TOKEN` from `~/.openclaw/openclaw.env` at runtime and
load `ws` from the OpenClaw install, so there is nothing to `npm install`.

    node gw-probe.mjs
    node gw-stream.mjs "قداش الوقت؟"

## What Phase 1 established

**The transport already exists.** The gateway binds to `loopback:18789` and the Pi
already runs `openclaw-tunnel.service`, so a WebSocket upgrade from the Pi returns
`101 Switching Protocols` today. No new port, no new credential, no LAN exposure.

**The build has everything the streaming path needs** — protocol 4, 218 methods,
30 events. `chat.send`, `chat.abort`, `sessions.abort`, `sessions.subscribe`,
`tools.invoke` and the `chat` / `session.tool` / `session.message` events are all
advertised.

## Four things that cost time to discover

**`client.id` and `client.mode` are enums.** A connect with arbitrary values is
rejected with `INVALID_REQUEST`. A headless backend uses `id: "gateway-client"`,
`mode: "backend"`.

**`chat.send` is asynchronous.** It returns `{runId, status: "started"}` in about
100 ms and the turn continues in the background. The reply arrives as events; a
client that treats the response as the answer gets nothing.

**Operator connections are broadcast.** `chat` and `session.tool` events arrive for
*every* session, not only the one you sent to — subscribing does not scope them.
Without filtering on `runId`, a concurrent turn from the voice loop or a heartbeat
bleeds its tokens into yours. This failed 4 of 10 verification turns before the
filter went in, with impossibly fast first-delta times as the symptom.

**`message` is an object, not a string.** `{role, content}`, where `content` is a
string *or* an array of parts. `deltaText` is the increment; `message` is the
cumulative snapshot; a non-prefix rewrite sets `replace=true` and puts the whole
replacement in `deltaText`.

## Measured, 30 August 2026

Ten turns, distinct session keys, including turns that call tools:

| | |
| --- | --- |
| deltaText concatenation == final message | **10 / 10** |
| First delta, typical | **1.7 – 2.7 s** |
| First delta, turn with 3 tool calls | 7.9 s |
| Total turn | 2.6 – 11.1 s |

**The ~2.5 s first-delta figure is the real floor for time-to-first-audio**, and it
is higher than the 0.9 s the plan projected. Prompt assembly, prefill and the first
tokens all land before that first delta. Adding Piper (0.07 s) and A2DP (~0.2 s)
puts a realistic target near **2.8 s**, against 5.6 s today — a 2x improvement, not
the 4x originally estimated. Later phases are measured against this number, not
against the projection.

## Known case to handle

Two of the ten turns produced zero deltas and an empty final message. The match held
because both sides were empty, but a turn that yields no deltas yields no speech.
The orchestrator must fall back to the assistant message on `session.message` when a
run completes without any delta.

## Not adopted

`queueMode` appears throughout the runtime but is **not** a `chat.send` parameter in
this build — the schema sets `additionalProperties: false` and the value is resolved
from config and directives. Interruption goes through `chat.abort` or
`sessions.abort`, both advertised.

`idempotencyKey` is **required** on every `chat.send`, not optional.


---

# Phase 2 — the orchestrator

**Not wired into the Pi.** The voice loop still runs the old path; this listens on
`127.0.0.1:18790` beside it and nothing depends on it yet.

    POST /turn         WAV in -> one WAV out (blocking, the old shape)
    POST /turn/stream  WAV in -> length-prefixed frames, one per sentence
    GET  /health

Stream frames are `[1 byte kind][4 byte big-endian length][body]`, kind 1 =
transcript JSON, 2 = WAV chunk, 3 = end JSON with the reply and timings.

## Measured, six consecutive short turns

| | warm |
| --- | --- |
| STT (Vosk, 1.5 s clip) | 164 – 225 ms |
| First token from the gateway | 1069 – 1186 ms |
| **First audio out** | **2305 – 2535 ms** |
| Whole turn | 4306 – 4491 ms |

Against a 5.6 s baseline, first audio lands at about **2.4 s**. The first turn after
a restart costs 8777 ms to first token — that is the cold prompt cache, and it
matches the 8.4 s cold prefill measured on the inference host exactly.

## The finding that matters more than the number

**On a one-sentence reply, streaming buys almost nothing.** First audio lands when
generation finishes, because there is no earlier sentence boundary to cut at.
Dropping the first-chunk limit from 70 characters to 36 changed nothing: the whole
reply was 27 characters. The 5.6 s to 2.4 s improvement is mostly the removal of
three SSH round trips and the Pi's own sequencing — not streaming.

Streaming earns its keep on long replies. On a 16-sentence answer, audio started at
the first sentence instead of the last, with chunks arriving steadily from 11 s to
26 s.

So the voice brevity rule in `AGENTS.md` and this work pull against each other. The
rule exists to protect time-to-*last*-word, and it is why replies are one sentence.
Relaxing it is what converts this pipeline into a felt improvement.

**Time to first token dominates everything else.** It ranged from 1.1 s on a plain
question to 10.3 s on a turn that read files first. Audio follows the first token by
a steady ~1.2 s regardless. The `session.tool` filler cue is therefore not a nicety:
it is the only thing that covers a ten-second silence while the agent works.

## Details worth keeping

**Node's first fetch cost 2.4 s** on a call that takes 180 ms warm — lazy HTTP stack
initialisation. The service now warms STT and TTS at startup, in about 30 ms.

**Piper returns a complete RIFF file per sentence.** Concatenating them would leave
a 44-byte header in the middle of the audio, which is an audible click, so `/turn`
takes the header from the first part and appends only `data` payloads.

**A colon is a sentence terminator here.** Excluding it delayed first audio by ten
seconds on a reply that opened with a colon-led preamble. The Arabic comma `،` is
not a terminator — Derja runs long comma-joined clauses — but it is the preferred
place to force a cut in an over-long run, because it is where a speaker breathes.

**Cutting at end-of-buffer is unsafe while streaming.** The next delta may continue
the sentence; `19:` + `09.` split into two utterances before this was fixed. Only a
flush may cut at the end of what has arrived.

---

# Phase 2.3 and 3 — wired in

The Pi now sends the recording to `/turn/stream` and plays each sentence as it
lands. Set `ORCHESTRATOR_URL` in `voicepi.env` to use it; **comment it out and the
loop falls back to the direct path**, which is still fully present. If the
orchestrator cannot be reached at all the loop falls back on its own, mid-turn,
rather than leaving the household with silence.

Live turn, measured through the microphone:

    stt 3013ms  first-token 1280ms  first-audio 5385ms  total 7386ms

STT is long there because the test recording was 21.5 s of clipped audio played at
the microphone; a normal turn measures 160–400 ms.

## What moved to the orchestrator

**Trigger stripping.** The Pi used to strip the wake word before sending, because
it did its own STT. STT is server-side now, so the Pi passes `WAKE_CANDIDATES` and
`WAKE_WORDS` in a header and the orchestrator strips them, folding the same forms
the wake matcher folds so عبّاس, عباس and Abbes all match.

That header is **percent-encoded**: HTTP headers are latin-1 and the wake words are
Arabic. Sending them raw raises `'latin-1' codec can't encode characters`, which is
exactly how the first live turn failed.

**Playback.** One `pw-cat --playback -` per turn, fed raw PCM, instead of one
`pw-play` per file. The acknowledgement tone goes through the same stream as the
reply, so the two cannot overlap and the sink opens exactly once. Combined with the
WirePlumber `session.suspend-timeout-seconds = 0` rule, the sink never suspends
between sentences.

## Phase 3 — write-once guards

`bin/_dedupe.sh`, sourced by `grocery.sh`, `baby-log.sh` and `calendar.sh`.

The model composes these command lines, so there is no turn id to thread through
from the orchestrator. The guard is content-based instead: the same verb with the
same arguments inside `DEDUPE_WINDOW_SECS` (default 90) is treated as the same
write and becomes a no-op that says so. Set the window to 0 to disable it.

The window is short on purpose. "Add milk" twice in a minute is a retry; twice in
an afternoon is two errands.

This is what decouples "did the stream survive" from "did the side effect land",
which is the thing that forced the never-retry rule in the first place.

## Still to do

- Filler cue on `session.tool`. The orchestrator sees the event and logs it; it
  does not yet emit a cue frame, and the Pi does not yet hold filler clips. This is
  the highest-value remaining item: first token took 10.3 s on a turn that read
  files, and nothing covers that silence.
- Shorten `WAKE_MUTE_TAIL_SECS` from its 1.5 s guess now that the persistent stream
  can report real drain timing.
- Input streaming (Phase 4) and barge-in (Phase 5).
