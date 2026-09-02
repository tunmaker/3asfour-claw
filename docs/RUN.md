# RUN.md — operations

Operational reference for a deployment of this assistant.

## 1. Components

Runs as a dedicated non-root user with systemd user units and lingering enabled,
so services start at boot without a login.

| Unit | Purpose |
|---|---|
| `openclaw-gateway.service` | The agent and its Control UI |
| `radicale.service` | CalDAV calendar |
| `abbes-backup.timer` | Nightly data backup |

Inference is provided by a separate machine on the LAN and is never bundled here:
an OpenAI-compatible chat endpoint, a speech-to-text endpoint, an embedding
endpoint for memory search, and a search MCP server. All four addresses are
configured, not hardcoded.

## 2. Configuration

Two files, neither of them in this repository:

- `~/.openclaw/openclaw.json` — agent configuration. Start from
  `abbes/openclaw.json.template` and replace `LLAMA_SERVER_IP` with the address of
  your inference host.
- `~/.openclaw/openclaw.env` — secrets and site paths, mode 600. Start from
  `.env.example`.

Secrets are referenced from the agent config as SecretRef objects, so no
credential is ever written into a config file in plaintext.

Every site-specific path lives in the env file. The scripts refuse to run rather
than guessing a default, so a missing variable fails loudly at the first call
instead of silently writing to the wrong place.

| Variable | Meaning |
|---|---|
| `ABBES_VAULT_ROOT` | Root of the Obsidian vault |
| `ABBES_VAULT_DIR` | The agent's folder inside the vault |
| `ABBES_VAULT_MOUNT` | Mountpoint that must be live before any vault write |
| `ABBES_DATA_DIR` | Local runtime data (default `/var/lib/abbes`) |
| `ABBES_BACKUP_DEST` | Backup destination |
| `ABBES_BACKUP_MOUNT` | Mountpoint that must be live before backing up |
| `ABBES_SPEAKER_SSH` | `user@host` of the voice satellite |
| `ABBES_SPEAKER_KEY` | Private key for the satellite's volume forced command |

## 3. Access

The Control UI requires a secure browser context. A plain-HTTP origin on a LAN
address does not qualify, so the gateway binds loopback and is reached over an SSH
tunnel:

```bash
ssh -f -N -L 18789:127.0.0.1:18789 <user>@<host>
```

then open `http://127.0.0.1:18789` and supply the gateway token. Because the token
is a SecretRef, the CLI will not embed it in a URL; paste it once and the browser
remembers it.

## 4. Agent tools

These are the scripts the agent is told about. They are the tools it has a reason
to run, not a boundary -- see the note on exec policy below.

| Script | Purpose |
|---|---|
| `note-add.sh`, `note-search.sh` | Notes in the vault |
| grocy (MCP) | Grocery list and pantry, served by the Grocy instance on this host. List-building only — no purchasing capability |
| `calendar.sh` | CalDAV read and write |
| `baby.sh` | Baby journal: feeds, sleep, diapers, notes. Fills in what was not said and prints what it assumed |
| `quran.sh` | Read-only retrieval from a local Qur'an text |
| `prayer.sh`, `weather.sh`, `look.sh` | Prayer times (computed locally), Open-Meteo weather, the camera |
| `whisper-transcribe.sh` | Speech-to-text |
| `speaker.sh` | Volume of the agent's own speech on the voice satellite |

**Exec runs unrestricted (`tools.exec.mode: "full"`).** This is deliberate, and it
replaced an allowlist that had quietly stopped working.

The scripts were declared as `tools.exec.safeBins`, which is the wrong mechanism
for them: safeBins is for stdin-only filters like `jq` and `grep`, and 2026.8.1
began enforcing that. It requires a `tools.exec.safeBinProfiles.<bin>` entry per
binary, refuses a `safeBinTrustedDirs` entry that is group-writable, and validates
each argument -- rejecting anything containing a slash or a glob character, and
offering no way to declare a boolean long flag such as `calendar.sh --iso`
(the profile schema is strict and has only `minPositional`, `maxPositional`,
`allowedValueFlags`, `deniedFlags`). Free-form Arabic note text and place names do
not survive that. Every tool call failed with `exec denied: allowlist miss` for as
long as it took to notice.

So the containment is no longer in the exec policy, and pretending otherwise would
be worse than not having it. What actually contains this agent:

- It runs in a container, on a LAN, with no cloud provider and no network tools.
- Vault write access is a filesystem permission, not an instruction.
- `speaker.sh` reaches the satellite through a `restrict,command=` SSH key that can
  only adjust volume.

Restoring a real allowlist means per-script `safeBinProfiles` plus `chmod 755` on
`~/bin`, and accepting that arguments with slashes will be refused.

Two design rules matter, because the model will otherwise report success it did not
achieve:

- Write tools print the record they stored and verify it after writing, so the
  agent quotes back what is really on disk.
- `quran.sh` only ever prints text found in the source file. A verse that cannot be
  retrieved is refused, never approximated.

## 5. Data and storage

| Location | Contents |
|---|---|
| `$ABBES_VAULT_DIR` | Notes — the single source of truth |
| `/var/www/grocy/data/` | Grocy database (groceries and pantry) |
| `$ABBES_DATA_DIR/babylog/journal.jsonl` | Baby journal, append-only, one event per line |
| `$ABBES_DATA_DIR/reference/quran/` | Qur'an text, if installed |
| `~/.openclaw/workspace/` | System prompt, identity, memory |
| `~/.local/share/radicale/` | Calendar events |

**No runtime data is stored inside this repository.** The working tree contains
only code, configuration templates, and documentation.

The Qur'an text is not distributed here. Install a plain-text Uthmani source at
`$ABBES_DATA_DIR/reference/quran/quran-uthmani.txt`, read-only. Until then
`quran.sh` refuses every request, which is the intended failure mode.

## 6. Backups

`abbes-backup.timer` runs nightly and copies the baby log, workspace, calendar
collections, and agent config to `$ABBES_BACKUP_DEST`, plus a dated tarball kept 30
days. If the destination is not mounted it exits 75 without writing anything.

`openclaw.env` is deliberately excluded, so a rebuild needs that file recreated by
hand from `.env.example`.

Restore has not been exercised end to end; treat the first restore as an untested
path.

## 7. Security model

- No cloud AI provider. The model catalogue resolves to a single local model, and
  the configuration uses replace semantics so unconfigured providers cannot appear.
- Web search and browser tools are denied for the agent.
- One chat channel: WhatsApp, via the external `@openclaw/whatsapp` plugin
  (Baileys, QR-linked to the household's personal number in self-chat mode:
  Abbes answers in the "message yourself" chat). DMs are allowlist-only, keyed
  off the linked number; the number lives in the host config, never here.
  Groups are allowlist-only and the allowlist is empty. Keep the plugin version
  matched to the runtime: the plugin's peer range is enforced at install time.
- Exec is unrestricted (`mode: "full"`). See section 4 for why, and for what
  carries the containment instead.
- The gateway binds loopback and is reached over SSH.
- The agent's write access to the vault is enforced by filesystem permissions, not
  by instructions in the prompt: it can read the vault and write only inside its own
  folder.
- Reaching the voice satellite is enforced the same way. `speaker.sh` uses a key
  whose `authorized_keys` entry is `restrict,command="/usr/local/bin/abbes-volume"`,
  so that key can only adjust the speaker volume: it gets no shell, no pty and no
  forwarding, and the command itself pattern-matches every argument before it
  reaches `pactl`.

Assume the model is susceptible to prompt injection from any text it ingests. With
exec unrestricted, the mitigations that remain are the container boundary, the
absence of any network-reaching tool, and the filesystem permissions above. Anything
that would widen those -- enabling web fetch, mounting the vault writable, giving the
satellite key a shell -- is a bigger decision than it looks.

## 8. Common operations

The gateway unit runs with `PrivateTmp=true`: a command the agent runs through
`exec` sees a different `/tmp` than your shell does. When debugging a tool from
the agent side, write its logs under `$HOME`, not `/tmp`, or they will appear to
vanish.

A tool script must not `exec` into a program that closes inherited file
descriptors (OpenSSH does). The exec supervisor watches an inherited pipe to
know the command tree is alive, and treats its early close as the tree having
died: the group is SIGTERMed 100ms later. Run such programs as a child of the
script instead. `speaker.sh` is the worked example.

```bash
systemctl --user status openclaw-gateway
journalctl --user -u openclaw-gateway -f

openclaw config validate
openclaw models list          # expect exactly one, local
openclaw doctor
openclaw security audit
openclaw memory index --force # after editing workspace documents
```

Change configuration with `openclaw config patch --stdin --dry-run` first; do not
hand-edit `openclaw.json` while the gateway is running.
