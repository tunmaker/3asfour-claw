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

Capture short notes from chat and find them again later. Notes live in
`notes/YYYY-MM-DD.md` inside the workspace, one bullet per note, time-stamped.

## Filing a note

When the user says something like "note that…", "rappelle-moi que…", "jot this
down", or "garde ça", file it:

```bash
/home/openclaw/bin/note-add.sh "Rappeler le garagiste au sujet du contrôle technique"
```

Write the note in **the language the user used**. Keep the user's own wording —
do not translate, summarise, or editorialise. Strip only the instruction itself
("note that", "n'oublie pas de") and keep the substance.

Confirm briefly with the file it landed in. Do not read the whole note file back.

## Searching notes

```bash
/home/openclaw/bin/note-search.sh "garagiste"
```

The search is case-insensitive and covers every dated note file. It prints
`file:line: text`. When reporting matches, give the date and the note text, not
the raw path. If nothing matches, say so plainly and offer to search a different
term rather than guessing.

## Boundaries

- Only ever write into `notes/`. Never modify notes the user did not ask you to
  change, and never delete a note file.
- If a request would rewrite an existing note, show the current text and ask
  first.

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
