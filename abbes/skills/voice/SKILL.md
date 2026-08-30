---
name: voice
description: "Speak through the household voice satellite and control the volume of your own speech."
metadata:
  {
    "openclaw":
      {
        "emoji": "🔊",
        "requires": { "bins": ["speaker.sh"] },
      },
  }
---

# Voice

Some turns reach you from the voice satellite — a Raspberry Pi in the house that
listens for your name, transcribes what was said, and speaks your reply out loud
through a speaker. Those sessions use the session key `voice`.

## Changing your own volume

```bash
/home/openclaw/bin/speaker.sh get           # current volume, 0-100
/home/openclaw/bin/speaker.sh down          # one step quieter
/home/openclaw/bin/speaker.sh up            # one step louder
/home/openclaw/bin/speaker.sh set 10        # an exact level
/home/openclaw/bin/speaker.sh mute
/home/openclaw/bin/speaker.sh unmute
```

Use it whenever someone asks you to be louder or quieter, or says they cannot
hear you or that you are too loud. `up` and `down` move in steps of 10 by
default; prefer them over `set` unless a specific level was asked for.

The command prints the level it actually reached. **Say that number back.** If it
prints `volume 10%`, you are at 10 — do not claim otherwise, and do not guess a
level you did not read.

## Boundaries

This controls the speaker's volume and nothing else. The key it uses is bound to
a forced command on the satellite and cannot run anything else on that host.

- Never claim to have changed the volume unless the command ran and succeeded.
- If it fails, say plainly that you could not reach the speaker, and report the
  error. A confident false confirmation is worse than an honest failure.
- Muting yourself means nobody can hear your replies. Do it when asked, say that
  you have done it, and remember that only `unmute` or the volume control on the
  speaker itself will bring you back.

## Volume is shared, and the house may be asleep

One speaker serves the whole household. Late at night, lean quiet: if someone
asks you to be louder after 23:00, do it, but do not raise the volume on your own
initiative at any hour.
