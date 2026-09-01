// Create or refresh the proactive cron jobs. Idempotent: run it as often as you
// like.
//
//   node cron/install-jobs.mjs [--dry-run]
//
// Jobs live in the gateway's SQLite state, not in this repo, so this script is
// the version-controlled definition of them. Editing a trigger script here and
// re-running this is how a change reaches the running system.
//
// Delivery is a webhook to the orchestrator's announce lane rather than a chat
// channel, because this gateway has no channels configured -- the only way Abbes
// reaches a person is the speaker in the room.

import { GatewayClient, readToken } from "../orchestrator/gateway-client.mjs";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const ENV_FILE = process.env.OPENCLAW_ENV || `${process.env.HOME}/.openclaw/openclaw.env`;
const GW_URL = process.env.GW_URL || "ws://127.0.0.1:18789";
const ANNOUNCE = process.env.ANNOUNCE_URL || "http://127.0.0.1:18790/announce";
const DRY = process.argv.includes("--dry-run");

const log = (...a) => console.log(...a);

const script = (name) => readFileSync(join(HERE, name), "utf8");

// Command payloads, not agent turns.
//
// The first version routed these through the model in a dedicated autonomy
// session. It worked -- trigger fired, correct slot, no history pollution --
// and it was still wrong: the sentence is already known before the job starts,
// so the model spent 33.7 seconds and answered "سأقوم بتنبيهك" ("I will alert
// you"), an acknowledgement rather than the announcement. A fixed time needs no
// judgement, so it gets no model, and the wording stops being a lottery.
//
// The model is still there for the things that do need judgement. This is not
// one of them.
//
// A command that prints only NO_REPLY posts nothing, which is how these stay
// silent on the minutes where the trigger fired but the situation has since
// changed.
const base = {
  sessionTarget: "isolated",
  delivery: { mode: "none" },
};

const JOBS = [
  {
    name: "abbes-prayer",
    schedule: { kind: "every", everyMs: 60000 },
    trigger: { script: script("prayer-trigger.js"), once: false },
    command: "announce-prayer.sh",
  },
  {
    name: "abbes-calendar",
    schedule: { kind: "every", everyMs: 60000 },
    trigger: { script: script("calendar-trigger.js"), once: false },
    command: "announce-calendar.sh",
  },
];

const gw = new GatewayClient({
  url: GW_URL, envFile: ENV_FILE, log: () => {},
  scopes: ["operator.read", "operator.write", "operator.admin"],
});

async function main() {
  await gw.connect();
  const existing = await gw.call("cron.list", {}).catch((e) => {
    throw new Error(`cron.list failed (is cron enabled?): ${e.message}`);
  });
  const jobs = existing?.jobs ?? existing?.result?.jobs ?? existing ?? [];
  const byName = new Map((Array.isArray(jobs) ? jobs : []).map((j) => [j.name, j]));

  for (const def of JOBS) {
    const spec = {
      name: def.name,
      enabled: true,
      schedule: def.schedule,
      trigger: def.trigger,
      sessionTarget: base.sessionTarget,
      // The script names itself to the announce lane, so quiet hours can exempt
      // one job without exempting proactive speech in general.
      payload: { kind: "command", argv: ["sh", "-lc", `$HOME/bin/${def.command}`], timeoutSeconds: 120 },
      delivery: base.delivery,
    };
    const found = byName.get(def.name);
    if (DRY) {
      log(`${found ? "would update" : "would create"} ${def.name}`);
      continue;
    }
    if (found) {
      // update takes {jobId, patch}, unlike add which takes the job inline.
      await gw.call("cron.update", { jobId: found.id, patch: spec });
      log(`updated ${def.name} (${found.id})`);
    } else {
      const res = await gw.call("cron.add", spec);
      log(`created ${def.name} (${res?.id ?? res?.job?.id ?? "?"})`);
    }
  }

  const after = await gw.call("cron.list", {});
  const list = after?.jobs ?? after ?? [];
  for (const j of Array.isArray(list) ? list : []) {
    log(`  ${j.enabled === false ? "off" : "on "}  ${j.name}  ${JSON.stringify(j.schedule)}`);
  }
  process.exit(0);
}

main().catch((e) => { console.error("install-jobs:", e.message); process.exit(1); });
