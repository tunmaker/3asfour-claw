# containers/ — Baby Buddy and its MCP server

Two rootless podman containers on the gateway host, managed as systemd user units
through quadlet. `deploy.sh` installs the unit files into
`~/.config/containers/systemd/`; podman's generator turns each into a service on
`systemctl --user daemon-reload`.

| Unit | What it is | Listens on |
| --- | --- | --- |
| `babybuddy.service` | Baby Buddy web UI and REST API (`lscr.io/linuxserver/babybuddy`) | `:8000`, LAN |
| `babybuddy-mcp.service` | The official MCP server, HTTP transport, `/mcp/` | `127.0.0.1:8081` |

Both use `Network=host`, so they share the host's network stack and the MCP server
reaches Baby Buddy over loopback. The MCP server binds `127.0.0.1` because OpenClaw
runs on the same host; only the web UI is reachable from the LAN, and nothing is
exposed off it.

Host networking is not just a simplification: on an unprivileged LXC guest there is
no `/dev/net`, and a private podman network needs `/dev/net/tun` for
slirp4netns/pasta. Giving each container its own namespace would mean changing the
LXC on the hypervisor; sharing the host's is enough for two local services.

## One-time host setup

**1. Rootless podman inside an LXC guest.** Install
`podman uidmap slirp4netns fuse-overlayfs netavark aardvark-dns`, then, as root:

```bash
usermod --add-subuids 10000-59999 --add-subgids 10000-59999 <user>
```

The guest maps 65536 uids, so the distribution's default subuid range
(`100000:65536`) falls outside it and `newuidmap` fails with `Operation not
permitted`. Remove any pre-existing `100000:65536` line for that user from
`/etc/subuid` and `/etc/subgid`, then run `podman system migrate` as the service
user.

**2. AppArmor.** Ubuntu 24.04 ships a name-only profile per userns-creating binary,
each `flags=(unconfined)` and meant to allow everything. Inside a nested apparmor
namespace they nonetheless mediate networking, so every `AF_INET` socket is refused
with `EACCES` — image pulls fail, and so does anything the container tries to
reach. Restore the intent through each profile's own override hook, as root:

```bash
for p in podman crun runc buildah slirp4netns rootlesskit; do
    printf 'network,\n' > /etc/apparmor.d/local/$p
    apparmor_parser -r /etc/apparmor.d/$p
done
```

**3. Directories and configuration.**

```bash
mkdir -p ~/containers/babybuddy/config ~/.config/babybuddy ~/.config/babybuddy-mcp
cp containers/babybuddy.env.example ~/.config/babybuddy/env
cp containers/babybuddy-mcp.env.example ~/.config/babybuddy-mcp/env
chmod 600 ~/.config/babybuddy-mcp/env
```

Fill in `TZ` and `CSRF_TRUSTED_ORIGINS` — every address the UI is opened at, or
Django rejects logins.

**4. Build the MCP image.** The project publishes no image, so it is built from a
pinned commit:

```bash
containers/build-babybuddy-mcp.sh
```

**5. Start Baby Buddy and move it off port 80.**

```bash
systemctl --user start babybuddy
```

The image's nginx listens on 80, 443 and 8000 from one server block. Under host
networking the first two cannot be bound — rootless cannot take a privileged port,
and the host already serves Grocy on 80 — so nginx fails in a loop until they are
removed. They are the only `default_server` lines, and the file lives on the volume:

```bash
podman exec babybuddy sed -i '/default_server;/d' /config/nginx/site-confs/default.conf
systemctl --user restart babybuddy
```

The image writes `default.conf` only when it is missing, so this survives updates;
`default.conf.sample` keeps the pristine copy.

**6. Give the assistant its own API user.** Log in to the UI (the image's initial
credentials are `admin` / `admin`), change that password, and add the child. The
assistant then gets a separate non-admin user, so what it may do is enforced by the
server and not only by the agent's allowlist: view everywhere, add where it should
log, and `change_timer` so a timer can be restarted — no change or delete on any
entry. Create it with `manage.py shell`, grant those permissions, mint its DRF
token, and write the token into `~/.config/babybuddy-mcp/env` without echoing it.
Then:

```bash
systemctl --user start babybuddy-mcp
```

**7. Register it with the agent** — see `docs/RUN.md`, section 10.

## Gotchas worth knowing

- **The API reads naive timestamps as UTC.** `babybuddy/settings/base.py` hardcodes
  `TIME_ZONE = "UTC"`, and token users are resolved after the middleware that would
  activate a user's timezone, so a local time sent without an offset is stored hours
  away and a time later today is rejected as "in the future". Every timestamp needs
  its offset (`2026-09-27T10:30:00+02:00`). `abbes/AGENTS.md` tells the agent so.
- **Tools take `child_id`, an integer**, from `children_list_children` — not the
  slug the MCP server's README advertises.
- **The MCP endpoint is `/mcp/`**, and `/mcp` answers with a 307 redirect. OpenClaw
  follows it; a hand-written client may not.
- **`/config` belongs to the container's mapped uid**, so the service user cannot
  edit it from the host — go through `podman exec`.

## Operations

```bash
systemctl --user status babybuddy babybuddy-mcp
journalctl --user -u babybuddy-mcp -n 50
podman ps
```

Baby Buddy updates itself to the current `latest` on restart. The MCP server does
not: bump `BABYBUDDY_MCP_REF` in the build script, rebuild, restart.

All state is the SQLite database under `~/containers/babybuddy/config`. It is
household data: it stays on the host, out of this repository, and out of logs.
