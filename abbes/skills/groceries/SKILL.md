---
name: groceries
description: "Grocery list, pantry, recipes and meal plans via the grocy tools. List-building only, no purchasing authority."
metadata:
  {
    "openclaw":
      {
        "emoji": "🛒",
      },
  }
---

# Groceries, pantry, recipes, meal plans

The household runs Grocy. Use the `grocy` MCP tools — never exec, never edit
files:

- `shopping_list_view` — always check before adding; `milk` already there
  means do not add it again.
- `shopping_list_add` / `shopping_list_remove` / `shopping_list_set_amount` /
  `shopping_list_set_note` / `shopping_list_clear`
- `stock_overview` / `stock_search` / `stock_expiring` — what the pantry holds
  and what is about to expire.
- `stock_add` / `stock_consume` — only when told something was bought or used.
- `recipes_list` / `recipe_details` / `recipe_fulfillment` — what can be cooked
  from what is in stock. `recipe_add_to_shopping` puts the missing ingredients
  on the list; `recipe_consume` deducts them after cooking, only when told the
  dish was actually made.
- `meal_plan_list` / `meal_plan_summary` / `meal_plan_add` / `meal_plan_remove`
  — the week's plan; `meal_plan_shopping` adds a planned day's needs to the
  list.

Items in English, metric quantities, prices in EUR. Most items are not in the
product catalog — add them as free-text notes with `entity_create`:

    entity: shopping_list
    data: {"note": "tomatoes", "amount": 1, "shopping_list_id": 1}

Use `shopping_list_add` only when the product already exists by that name; if
it answers "not found", fall back to the note row above — never ask the person
what the product is called.

The dietary rules in `USER.md` are mandatory for every suggestion and
substitution. Swap and say what you swapped; never silently omit; mark a doubtful
product `(verify)`.

This builds a list. It has **no purchasing or payment authority**: never order,
buy, reserve or pay, and say so if asked.
