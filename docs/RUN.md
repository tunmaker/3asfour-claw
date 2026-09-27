# RUN.md — operations

Operational reference for a deployment of this assistant.

## 1. Components

Runs as a dedicated non-root user with systemd user units and lingering enabled,
so services start at boot without a login.

| Unit | Purpose |
|---|---|
| `openclaw-gateway.service` | The agent and its Control UI |
| `abbes-orchestrator.service` | The voice path: whisper -> gateway -> Piper, on `127.0.0.1:18790` |
| `radicale.service` | CalDAV calendar (a data service; the agent has no calendar tool) |
| `babybuddy.service` | Baby Buddy, in rootless podman — web UI and REST API on `:8000` |
| `babybuddy-mcp.service` | Its MCP server, HTTP transport, on `127.0.0.1:8081` |
| `abbes-backup.timer` | Nightly data backup |

Both podman units come from quadlet files in `containers/`; see
[containers/README.md](../containers/README.md) for the one-time host setup.

Inference runs on a separate machine on the LAN: the chat model, whisper
(speech-to-text), Piper (text-to-speech), embeddings for memory search, and the
open-websearch MCP server. Every address is
configured, not hardcoded.

## 2. Configuration

Two files, neither of them in this repository:

- `~/.openclaw/openclaw.json` — agent configuration. Start from
  `abbes/openclaw.json.template`.
- `~/.openclaw/openclaw.env` — secrets and endpoints, mode 600. Start from
  `.env.example`.

| Variable | Meaning |
|---|---|
| `LLAMACPP_API_KEY` | Key for the inference host, chat and embeddings |
| `OPENCLAW_GATEWAY_TOKEN` | Control UI authentication |
| `OPENCLAW_HOOK_TOKEN` | Inbound hooks; sessions must start with `hook:` |
| `WHISPER_URL` | whisper-server `/inference` endpoint |
| `PIPER_URL` | Piper server |
| `ABBES_DATA_DIR` | Local runtime data (default `/var/lib/abbes`) |
| `ABBES_BACKUP_DEST` | Backup destination |
| `ABBES_BACKUP_MOUNT` | Mountpoint that must be live before backing up |

Change configuration with `openclaw config patch --stdin --dry-run` first; do not
hand-edit `openclaw.json` while the gateway is running.

## 3. Access

The Control UI requires a secure browser context, so the gateway binds loopback
and is reached over an SSH tunnel:

```bash
ssh -f -N -L 18789:127.0.0.1:18789 <user>@<host>
```

then open `http://127.0.0.1:18789` and supply the gateway token.

## 4. The prompt and the tools

The prompt is `abbes/AGENTS.md` and `abbes/IDENTITY.md`, plus the private
`USER.md` on the host. Bundled skills are off (`skills: []`) and OpenClaw's
default SOUL.md and HEARTBEAT.md are not created. The whole system prompt with
tools is about 5,300 tokens.

Tools are an explicit allowlist (`tools.allow`): the grocy, jellyfin, babybuddy and
open-websearch MCP tools, `memory_search`/`memory_get`, and `write`/`edit`
restricted to the workspace (`tools.fs.workspaceOnly`). There is no exec, and the
built-in web providers stay denied: search goes through the self-hosted
open-websearch server only. Adding a tool means adding it to that list and to
AGENTS.md.

Voice turns reach the model prefixed `[voice]`, which is how AGENTS.md keeps
spoken replies short and free of markdown.

## 5. Latency

The model generates at about 6 tokens/s, so the reply length is the latency.

| | |
|---|---|
| whisper, short command | ~1.1 s |
| First audio, warm prompt cache | ~4.5–5 s |
| First audio, turn that calls a tool | ~20 s |
| Cold prompt (first turn after a llama-server restart) | ~50 s |

llama-server keeps evicted prompts in host RAM (`LLAMA_ARG_CACHE_RAM`), so a cron
job or another session taking the single slot costs a few seconds, not a cold
prefill.

## 6. Data and storage

| Location | Contents |
|---|---|
| `/var/www/grocy/data/` | Grocy database (groceries and pantry) |
| `~/containers/babybuddy/config/` | Baby Buddy database (the baby log) |
| `~/.openclaw/workspace/` | Prompt, identity, memory |
| `~/.local/share/radicale/` | Calendar events |

**No runtime data is stored inside this repository.**

## 7. Backups

`abbes-backup.timer` runs nightly and copies the workspace, calendar collections,
and agent config to `$ABBES_BACKUP_DEST`, plus a dated tarball kept 30 days. If
the destination is not mounted it exits 75 without writing anything.

`openclaw.env` is deliberately excluded, so a rebuild needs that file recreated by
hand from `.env.example`.

## 8. Security model

- No cloud AI provider. The model catalogue resolves to a single local model.
- The agent can call only the allowlisted tools; its only writes land in its own
  workspace, and its only internet access is the self-hosted search server.
- One chat channel: WhatsApp, via the `@openclaw/whatsapp` plugin in self-chat
  mode. DMs and groups are allowlist-only; numbers live in the host config.
- The gateway and the orchestrator bind loopback; the Pi reaches both over an SSH
  tunnel.

## 9. Common operations

```bash
systemctl --user status openclaw-gateway abbes-orchestrator
journalctl --user -u abbes-orchestrator -f     # one line per voice turn, with timings

openclaw config validate
openclaw models list          # expect exactly one, local
openclaw doctor
```

## 10. MCP servers (host-only setup)

Registered in `mcp.servers` with `openclaw mcp add`; recorded here because no
deploy script creates them.

- **grocy** — `~/.venvs/grocy-mcp/bin/grocy-mcp` (stdio). Grocy itself runs on
  this host: nginx + PHP-FPM serving `/var/www/grocy`, SQLite in
  `/var/www/grocy/data/`. API key in `~/.config/grocy-mcp/config.toml` (mode 600).
- **babybuddy** — `http://127.0.0.1:8081/mcp/` (streamable-http). The official
  server, running in podman next to Baby Buddy itself; both are managed by the
  quadlet units in `containers/`. Its API token is in
  `~/.config/babybuddy-mcp/env` (mode 600), not in the OpenClaw config. It serves 63
  tools; 12 are allowlisted — children, feedings, diapers, sleep, pumping and timers,
  `list_` and `create_` only. Tool schemas are expensive here (about 250 tokens each,
  and prefill runs at ~9 ms/token), so tummy time, notes and measurements are left
  out rather than paid for on every turn; each is one line in `tools.allow`. The
  assistant's Baby Buddy user has no change or delete permission either, so an entry
  cannot be rewritten even by mistake.
- **jellyfin** — `~/.local/bin/jellyfin-mcp` (stdio, official binary),
  `--disable-destructive --toolsets discovery,media,playback`. `JELLYFIN_URL`
  and `JELLYFIN_API_KEY` are set as env on the server entry.
- Playback lands on the Pi: `jellyfin-mpv-shim` runs as a user service on the
  voice satellite, registered in Jellyfin as the player **Abbes Pi**, logged in as
  a dedicated non-admin Jellyfin user. `~/.config/jellyfin-mpv-shim/mpv.conf`
  pins `vo=null` and the speakerphone sink. **That sink name is pinned in two
  places** — `voicepi.env` (`SPEAKER_SINK`) and `mpv.conf` — so changing the
  speaker means changing both, or music keeps playing to a sink nobody can hear.

After changing any server's config: `openclaw mcp reload`, then restart the
gateway. `openclaw mcp probe <name>` lists the live tool count.
