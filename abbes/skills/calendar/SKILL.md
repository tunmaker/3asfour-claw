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

Appointments live in a self-hosted Radicale CalDAV server on this machine
(`127.0.0.1:5232`, calendar `perso`). Nothing is synced to any cloud calendar.

```bash
/home/openclaw/bin/calendar.sh list 14                                  # next 14 days
/home/openclaw/bin/calendar.sh add "Dentiste" "2026-09-02 09:00" 30     # summary, start, minutes
/home/openclaw/bin/calendar.sh remove "Dentiste"                        # delete by summary match
```

## Conventions

- Times are **24-hour**, timezone **Europe/Paris**. Never write "2:30 PM".
- Dates passed to the script are always `YYYY-MM-DD HH:MM`. Convert whatever the
  user said ("mardi prochain à 14h30", "next Tuesday at 2:30pm") into that form
  yourself before calling the script.
- Duration defaults to 60 minutes when omitted.
- Keep the summary in **the language the user used**.

## Resolving relative dates

Work out the actual date before calling the script, and **state the resolved date
back to the user** when you confirm — "mardi 2 septembre à 09:00", not "next
Tuesday". That way a misread is caught immediately.

If the user's phrasing is genuinely ambiguous ("jeudi" when two Thursdays are
plausible), ask rather than guessing.

## Boundaries

- Never delete an appointment unless the user asked for that specific one.
  `remove` matches on a substring, so confirm which appointment you are about to
  delete when more than one could match.
- Do not invent attendees, locations, or video links that the user did not give.

## Never fake the result

These files are only ever modified through the script above. **Do not** write,
edit, or patch them with filesystem tools — the script sets the timestamp and
format, and hand-writing them corrupts both.

If the script fails, is denied, or you cannot run it: **say so plainly and stop.**
Report what you tried and the error you got. Never tell the user something was
saved, added, or scheduled unless the script actually ran and succeeded. A
confident false confirmation is far worse than an honest failure.

## Language of stored data

Whatever language the conversation is in, **the text you pass to the command below
must be English**. Translate it before calling the command, then answer the user in
their own language. Stored data stays consistent and searchable; the conversation does not.
