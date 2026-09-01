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

// Every job is an agent turn in the autonomy session. Never the voice session:
// proactive turns must not accumulate in the transcript the user talks to.
const base = {
  sessionTarget: "session:autonomy",
  payload: { kind: "agentTurn" },
  model: "llamacpp/qwen3.5-9b-q8-auto",
  // The URL goes in `to`, not `url`: the delivery schema is shared with the
  // chat channels, where `to` is the recipient.
  delivery: { mode: "webhook" },
};

const JOBS = [
  {
    name: "abbes-prayer",
    schedule: { kind: "every", everyMs: 60000 },
    trigger: { script: script("prayer-trigger.js"), once: false },
    message:
      "أعلن وقت الصلاة كما ورد أعلاه. جملة واحدة قصيرة بالعربية الفصحى فقط.",
  },
  {
    name: "abbes-calendar",
    schedule: { kind: "every", everyMs: 60000 },
    trigger: { script: script("calendar-trigger.js"), once: false },
    message:
      "ذكّر بالموعد كما ورد أعلاه. جملة واحدة قصيرة بالعربية الفصحى فقط.",
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
      payload: { ...base.payload, message: def.message, model: base.model },
      // Each job names itself in the URL so quiet hours can exempt one job
      // without exempting proactive speech in general.
      delivery: { ...base.delivery, to: `${ANNOUNCE}?source=cron:${def.name}` },
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
