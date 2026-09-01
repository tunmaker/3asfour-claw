---
name: calendar
description: "Read and add appointments in the local self-hosted CalDAV calendar."
metadata:
  {
    "openclaw":
      {
        "emoji": "📅",
        "requires": { "bins": ["calendar.sh"] },
      },
  }
---

# Calendar

A local Radicale server, calendar `perso`. Nothing syncs to any cloud.

```bash
/home/openclaw/bin/calendar.sh list 14                               # next 14 days
/home/openclaw/bin/calendar.sh add "Dentist" "2026-09-02 09:00" 30   # summary, start, minutes
/home/openclaw/bin/calendar.sh remove "Dentist"                      # by summary match
```

- Times are 24-hour, Europe/Paris, always `YYYY-MM-DD HH:MM`. Resolve "mardi
  prochain à 14h30" into that yourself, and **say the resolved date back** when
  confirming so a misread is caught. If two dates are plausible, ask.
- Duration defaults to 60 minutes. Summary in English.
- `remove` matches a substring: confirm which one when more than one could match.
  Never delete anything the user did not name.
- Do not invent attendees, places or links. Only the script writes these files.
