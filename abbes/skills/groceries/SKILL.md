---
name: groceries
description: "Maintain a running grocery list. List-building only, no purchasing authority."
metadata:
  {
    "openclaw":
      {
        "emoji": "🛒",
        "requires": { "bins": ["grocery.sh"] },
      },
  }
---

# Groceries

Maintain the running list in `groceries/list.md`.

```bash
/home/openclaw/bin/grocery.sh list             # show the current list
/home/openclaw/bin/grocery.sh add "lait 1L"    # add an item
/home/openclaw/bin/grocery.sh done "lait"      # check an item off
/home/openclaw/bin/grocery.sh remove "lait"    # delete an item outright
/home/openclaw/bin/grocery.sh clear            # drop everything already checked off
```

Add items in the language the user used. Keep quantities in metric and prices in
EUR.

## Dietary requirements

`USER.md` states the dietary rules for this household. They are **mandatory** and
apply to every suggestion, substitution, and added item, without being asked.

- Follow them for recipes and shopping suggestions alike.
- When a recipe calls for something the rules exclude, **substitute and say what you
  swapped**. Never silently omit it, and never add the excluded original.
- When you cannot tell whether a product complies, add it with a `(verifier)` marker
  rather than assuming either way.

## Boundaries — read this before acting

This skill builds a **list**. It has **no purchasing or payment authority**.

- Never order, buy, reserve, or pay for anything.
- Never visit a retailer's checkout, submit a cart, or use saved payment details.
- If the user asks you to actually buy something, say plainly that you can only
  build the list, and that they have not enabled purchasing.

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
