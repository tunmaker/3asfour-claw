# 3asfour-claw

A self-hosted household assistant built on OpenClaw, running entirely on local
inference. No cloud AI provider, no external search API.

Speaks Tunisian Derja (Arabic script), فصحى, French and English, mirroring whoever
it is talking to. Handles notes, appointments, grocery lists, a baby log, and
retrieval from a local Qur'an text.

## Design

- **Local inference only.** Chat, speech-to-text, embeddings and search are served
  by a separate machine on the LAN. The model catalogue resolves to a single local
  model and unconfigured providers cannot appear.
- **No general shell.** The agent may run a fixed allowlist of small scripts and
  nothing else.
- **Write tools return what they wrote.** A small model will otherwise confirm
  actions it did not perform, so every write verifies itself and prints the stored
  record.
- **Never generate scripture.** Qur'anic text is retrieved from a local source file
  or refused. It is never produced from the model's memory.

## Layout

| Path | Contents |
| --- | --- |
| `abbes/` | System prompt, identity files, skills, config template |
| `bin/` | The scripts the agent is allowed to execute |
| `systemd/` | User units for the gateway, calendar and backups |
| `docs/` | Operations reference |

No runtime data is stored in this repository. Notes and lists live in an Obsidian
vault; the baby log and reference texts live under `$ABBES_DATA_DIR`
(default `/var/lib/abbes`). Both are configured, never hardcoded.

## Setup

1. Install OpenClaw (Node 22+) as a dedicated non-root user.
2. Copy `abbes/openclaw.json.template` to `~/.openclaw/openclaw.json` and replace
   `LLAMA_SERVER_IP` with your inference host.
3. Copy `.env.example` to `~/.openclaw/openclaw.env`, fill it in, `chmod 600`.
4. Install the units from `systemd/` and enable lingering for the service user.
5. Copy `bin/` into place and allowlist the scripts for exec.

See [docs/RUN.md](docs/RUN.md) for operations, security model, and backups.

## Updating a deployment

This repository is the single source of truth. Edit and push from a working copy,
then on the host that runs the assistant:

```bash
git pull
./deploy.sh
```

`deploy.sh` installs the scripts, systemd units, prompt and skills into place,
reports what changed, and reloads systemd. It never touches `USER.md`, `MEMORY.md`,
or any data — those are private and live outside this repository.

## Qur'an text

Not distributed here. Install a plain-text Uthmani source at
`$ABBES_DATA_DIR/reference/quran/quran-uthmani.txt`, read-only to the agent. Until
then the tool refuses every request, which is the intended behaviour.

## Repository policy

Secrets and personal data never enter the working tree. Runtime data lives outside
the repository entirely, so no `git add` can reach it.

Enable the pre-commit hook immediately after cloning — git does not do it for you:

```bash
git config core.hooksPath .githooks
```

It blocks private and tailnet IP addresses, token and password assignments, key
material, and data file types.

[AGENTS.md](AGENTS.md) states the rules in full and applies to humans and coding
agents alike. Read it before contributing.
