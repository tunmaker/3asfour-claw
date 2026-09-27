# 3asfour-claw

A self-hosted household assistant built on OpenClaw, running entirely on local
inference. No cloud AI provider, no external search API.

It speaks English. You call it by name in the room, or write to it in the
Control UI or over WhatsApp. It keeps the grocery list and plays music, and
otherwise answers from the model.

## How a voice turn works

```
Pi:           wake word "Abbes" (Vosk, on the Pi) -> tone -> record until silence
                 | one HTTP request over the SSH tunnel
Orchestrator: whisper (speech -> text) -> OpenClaw voice session -> Piper, per sentence
                 | WAV frames stream back as each sentence renders
Pi:           play
```

whisper, Piper and the model run on the inference host
([intel-gpu-inference](https://github.com/tunmaker/intel-gpu-inference)).

## Layout

| Path | Contents |
| --- | --- |
| `abbes/` | The prompt (AGENTS.md, IDENTITY.md) and the config template |
| `orchestrator/` | The voice path on the gateway host: whisper -> gateway -> Piper |
| `pi/` | The voice satellite: wake word, recording, playback |
| `bin/` | Nightly backup, and the transcriber for WhatsApp voice notes |
| `systemd/` | User units for the gateway, calendar and backups |
| `containers/` | Quadlet units for Baby Buddy and its MCP server, in rootless podman |
| `docs/` | Operations reference |

## Tools

Four MCP servers: **grocy** for the shopping list and pantry, **jellyfin** for
music on the Pi speaker, **babybuddy** for the baby log, and **open-websearch**
(self-hosted on the inference host) for the web. Plus OpenClaw's own memory tools,
and `write`/`edit` confined
to the workspace so memory notes can be kept. The allowlist is `tools.allow` in
the config; there is no exec.

## Setup

1. Install OpenClaw (Node 22+) as a dedicated non-root user.
2. Copy `abbes/openclaw.json.template` to `~/.openclaw/openclaw.json`, replace
   `LLAMA_SERVER_IP`, and fill in the MCP servers (see docs/RUN.md).
3. Copy `.env.example` to `~/.openclaw/openclaw.env`, fill it in, `chmod 600`.
4. Enable lingering for the service user, then run `./deploy.sh`.
5. Set up the containers as described in [containers/README.md](containers/README.md).
6. Set up the Pi as described in [pi/README.md](pi/README.md).

## Updating a deployment

This repository is the single source of truth. On the host that runs the
assistant, from a checkout:

```bash
./deploy.sh
systemctl --user restart openclaw-gateway abbes-orchestrator
```

`deploy.sh` installs the prompt, the orchestrator, the scripts and the systemd
units, and reports what changed. It never touches `USER.md`, `MEMORY.md`, or any
data — those are private and live outside this repository.

## Repository policy

Secrets and personal data never enter the working tree. Enable the pre-commit
hook immediately after cloning:

```bash
git config core.hooksPath .githooks
```

[AGENTS.md](AGENTS.md) states the rules in full and applies to humans and coding
agents alike. Read it before contributing.
