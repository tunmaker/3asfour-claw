# orchestrator/ — the streaming voice path

Phase 1 of the streaming migration: proving the gateway's WebSocket control plane
can carry a voice turn, before anything is rewritten to depend on it.

Nothing here is wired into the running assistant yet. Both scripts are read-mostly
probes, run by hand on the gateway host.

| Script | What it does |
| --- | --- |
| `gw-probe.mjs` | Connects as an operator client and prints what this build advertises. Read-only. |
| `gw-stream.mjs` | Sends one turn and verifies the delta stream reconstructs the final message. |

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
