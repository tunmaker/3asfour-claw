# AGENTS.md — rules for working in this repository

This file governs anyone editing this repository: humans and coding agents alike.
It is not the assistant's system prompt — that lives in `abbes/AGENTS.md` and is a
different thing entirely.

This repository is **public**. It describes a household assistant that handles
personal data. The code is public; the data never is. Everything below exists to
keep that line intact.

---

## 1. Secrets — absolute

**No secret ever enters this repository, in any form, at any time.** Not in a
config file, not in a comment, not in a test fixture, not in an example, not
temporarily, not "obviously fake".

This covers API keys and tokens, passwords and password hashes, gateway and
session tokens, private keys and certificates, and htpasswd or bcrypt material.

The correct pattern is already established — follow it:

- Real values live in `~/.openclaw/openclaw.env`, mode 600, outside the tree.
- The agent config references them as SecretRef objects, never inline.
- `.env.example` carries **variable names only**, with `CHANGEME` as every value.

If you need a new secret, add its name to `.env.example` and read it from the
environment. Never add a default that happens to be the real value.

**If a secret is ever committed:** rotate it first, rewrite history second. Rotation
is the fix; rewriting is cleanup. A published secret must be treated as burned even
if the commit is removed minutes later — assume it was cloned.

## 2. Personal data — never in the tree

**No personal or household data lives inside this working tree, ever** — not even
gitignored. The rule is structural, not advisory: if data is not in the tree, no
mistake with `git add` can publish it.

Never commit, and never create inside this tree:

- Notes, grocery lists, calendar events, or any `.ics` / `.csv` produced by use
- The baby log, in any form
- Qur'an or other reference texts (licensing aside, they are not code)
- Names, ages, relationships, addresses, phone numbers, employers, schools
- Dietary, medical, religious, or political detail about the household
- Real IP addresses, tailnet addresses, hostnames, or mosque/service identifiers

Runtime data belongs in these places, all outside the tree:

| Data | Location |
|---|---|
| Baby log | Baby Buddy's database, in its container volume |
| Reference texts | `$ABBES_DATA_DIR` (default `/var/lib/abbes`) |
| Agent workspace, memory | `~/.openclaw/workspace/` |
| Calendar collections | `~/.local/share/radicale/` |
| Groceries and pantry | Grocy's database |

If you add a feature that writes data, it writes to one of those. **Do not create a
new writable directory inside the repository.** If you think you need one, that is
the signal to put it under `$ABBES_DATA_DIR` instead.

### Household policy belongs in USER.md

Personal policy — dietary rules, preferences, anything describing the people rather
than the software — goes in `~/.openclaw/workspace/USER.md`, which is injected into
every turn and is **not tracked**.

Skills and prompts in this repository reference that policy; they never restate it.
A skill saying "follow the dietary rules in `USER.md`" is correct. A skill listing
those rules is a leak, however useful it looks.

## 3. No site-specific values in code

Anything that describes *this* deployment is configuration, not code.

Every path, host, port, and address must come from the environment. Scripts must
**fail loudly on a missing variable** rather than fall back to a default:

```bash
DATA="${ABBES_DATA_DIR:?ABBES_DATA_DIR is not set (see .env.example)}"
```

Never write a fallback that encodes the author's own layout — `${VAR:-/mnt/nas/...}`
is a leak with a default attached, and it silently writes to the wrong place on
someone else's machine.

Documentation follows the same rule: write `$ABBES_DATA_DIR` or `<host>`, never a
real path or address.

## 4. The pre-commit hook is mandatory

The hook lives in `.githooks/pre-commit` and is tracked, but git does not enable it
automatically. **After cloning, run:**

```bash
git config core.hooksPath .githooks
```

It blocks private and tailnet IPs, token and password assignments, key material,
bcrypt hashes, `.env` files, and data file types.

**Never use `--no-verify`.** If the hook blocks you, it is right often enough that
the burden is on you to prove otherwise. A false positive is fixed by narrowing the
pattern in the hook, not by bypassing it — and that fix protects the next person.

The hook is a backstop for accidents, not a substitute for the rules above. Passing
it does not mean a change is safe to publish.

## 5. Before you commit

- Does this add a real path, host, address, or name? Move it to the environment.
- Does this describe a person rather than the software? It belongs in `USER.md`.
- Does this create a writable directory in the tree? Put it under `$ABBES_DATA_DIR`.
- Would a stranger reading this diff learn something about the household? Remove it.

## 6. Documentation

Documentation explains how to operate the software, not how this particular
deployment was built. Do not write migration narratives, incident histories, or
"we fixed X" notes into `docs/` — that is churn a reader does not need, and it tends
to carry site detail with it.

Keep `docs/RUN.md` current, generic, and short.
