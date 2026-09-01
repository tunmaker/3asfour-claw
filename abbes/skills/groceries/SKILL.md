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

```bash
/home/openclaw/bin/grocery.sh list
/home/openclaw/bin/grocery.sh add "milk 1L"
/home/openclaw/bin/grocery.sh done "milk"      # check off
/home/openclaw/bin/grocery.sh remove "milk"    # delete
/home/openclaw/bin/grocery.sh clear            # drop everything checked off
```

Items in English, metric quantities, prices in EUR. Check the list before adding:
`milk` already there means do not add it again.

The dietary rules in `USER.md` are mandatory for every suggestion and
substitution. Swap and say what you swapped; never silently omit; mark a doubtful
product `(verify)`.

This builds a list. It has **no purchasing or payment authority**: never order,
buy, reserve or pay, and say so if asked. Only the script writes this file.
