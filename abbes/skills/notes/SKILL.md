---
name: notes
description: "File a quick note from a chat message into dated markdown, and search past notes."
metadata:
  {
    "openclaw":
      {
        "emoji": "🗒️",
        "requires": { "bins": ["note-add.sh", "note-search.sh"] },
      },
  }
---

# Notes

"Note that…", "rappelle-moi que…", "garde ça" → file it, in English, keeping the
substance and dropping only the instruction words:

```bash
/home/openclaw/bin/note-add.sh "Call the garage about the inspection"
/home/openclaw/bin/note-search.sh "garage"
```

Confirm with the file it landed in; do not read the note file back. Search is
case-insensitive across every dated file and prints `file:line: text` — report the
date and the text, not the path. No match: say so, offer another term, never
guess.

Only ever write through `note-add.sh`, only into `notes/`. Never delete a note;
to change one, show the current text and ask first.
