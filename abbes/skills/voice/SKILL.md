---
name: voice
description: "Control the volume of your own speech on the household voice satellite."
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

```bash
/home/openclaw/bin/speaker.sh get        # 0-100
/home/openclaw/bin/speaker.sh up         # one step (10) louder
/home/openclaw/bin/speaker.sh down
/home/openclaw/bin/speaker.sh set 40
/home/openclaw/bin/speaker.sh mute | unmute
```

Any request to be louder or quieter runs this — prefer `up`/`down` unless an exact
level was asked for. **Say back the number it printed**, never one you assumed.
If it fails, say you could not reach the speaker.

One speaker serves the whole house. Raise the volume when asked, at any hour; never
on your own initiative. Muted means nobody hears you until `unmute`.
