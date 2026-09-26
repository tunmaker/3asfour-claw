# orchestrator/ — the voice path

Runs on the gateway host as `abbes-orchestrator.service`, bound to
`127.0.0.1:18790`. The Pi reaches it through its SSH tunnel.

    POST /turn/stream   WAV in -> length-prefixed frames out
    GET  /health

Frames are `[1 byte kind][4 byte big-endian length][body]`: kind 1 is the
transcript JSON, 2 is one WAV per sentence, 3 is the end JSON with the reply and
timings (`sttMs`, `firstDeltaMs`, `firstAudioMs`, `totalMs`).

| File | What it does |
| --- | --- |
| `abbes-orchestrator.mjs` | The service: whisper -> `chat.send` on the voice session -> Piper per sentence |
| `transcript.mjs` | Drops whisper's noise labels and phantom endings, and the wake word at the front |
| `gateway-client.mjs` | Persistent operator connection to the gateway; streams a turn's deltas |
| `sentences.mjs` | Cuts the token stream into speakable sentences |

Tests: `node --test`.

Configuration comes from `~/.openclaw/openclaw.env`: `WHISPER_URL` and
`PIPER_URL`. The unit maps them to `STT_URL` and `TTS_URL`.

## Behaviour worth knowing

- **Voice turns are prefixed `[voice]`.** AGENTS.md uses it to keep spoken
  replies short and plain.
- **The session resets after 30 idle minutes** (`ABBES_VOICE_IDLE_RESET_MS`).
  Voice history is worth minutes, not days, and a short session keeps prefill fast.
- **The wake word comes back in the transcript.** The Pi keeps a second of audio
  from before the trigger so a request said in one breath with the name is not
  clipped. The name is passed to whisper as its prompt, and a leading word close
  to it is dropped.
- **Whisper invents text on near-silence** — "Thank you.", "Thanks for
  watching!" — and labels noise as `[Music]`. Those become an empty request, and
  the Pi goes back to idle without calling the model.
- **`chat.send` is asynchronous.** The reply arrives as `chat` events, which are
  broadcast for every session, so the client filters on `runId`.
- **A client hang-up aborts the run**, so a turn nobody is listening to stops
  generating.
- **Piper returns a complete RIFF file per sentence.** The Pi plays each through
  one long-lived `pw-cat`, taking the format from the first.
