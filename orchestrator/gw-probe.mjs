// Phase 1.1 — connect to the OpenClaw gateway as an operator client and report
// what this build actually advertises. Read-only: no chat.send, no state change.
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
const require = createRequire("/home/openclaw/.npm-global/lib/node_modules/openclaw/");
const WebSocket = require("ws");

const URL = process.env.GW_URL || "ws://127.0.0.1:18789";
const ENV = process.env.OPENCLAW_ENV || `${process.env.HOME}/.openclaw/openclaw.env`;

function token() {
  if (process.env.OPENCLAW_GATEWAY_TOKEN) return process.env.OPENCLAW_GATEWAY_TOKEN;
  for (const line of readFileSync(ENV, "utf8").split("\n")) {
    const m = line.match(/^\s*OPENCLAW_GATEWAY_TOKEN=(.*)$/);
    if (m) return m[1].trim().replace(/^["']|["']$/g, "");
  }
  throw new Error("no OPENCLAW_GATEWAY_TOKEN in env or " + ENV);
}

const ws = new WebSocket(URL);
let sent = false;
const t0 = Date.now();

ws.on("open", () => console.log(`[${Date.now() - t0}ms] socket open -> ${URL}`));

ws.on("message", (raw) => {
  let f;
  try { f = JSON.parse(raw.toString()); } catch { return; }
  const ms = Date.now() - t0;

  if (f.type === "event" && f.event === "connect.challenge") {
    console.log(`[${ms}ms] connect.challenge received`);
    if (sent) return;
    sent = true;
    ws.send(JSON.stringify({
      type: "req", id: "1", method: "connect",
      params: {
        minProtocol: 4, maxProtocol: 4,
        client: { id: "gateway-client", version: "0.1.0", platform: "linux", mode: "backend" },
        role: "operator",
        scopes: ["operator.read", "operator.write"],
        caps: [], commands: [], permissions: {},
        auth: { token: token() },
        locale: "ar-TN",
        userAgent: "abbes-orchestrator-probe/0.1.0",
      },
    }));
    return;
  }

  if (f.type === "res" && f.id === "1") {
    if (!f.ok) {
      console.log(`[${ms}ms] CONNECT REJECTED:`, JSON.stringify(f.error));
      process.exit(1);
    }
    const p = f.payload || {};
    console.log(`[${ms}ms] hello-ok`);
    console.log("  protocol :", p.protocol);
    console.log("  server   :", p.server?.version, "connId", p.server?.connId);
    console.log("  role     :", p.auth?.role);
    console.log("  scopes   :", (p.auth?.scopes || []).join(", "));
    console.log("  policy   : maxPayload", p.policy?.maxPayload,
                "tick", p.policy?.tickIntervalMs + "ms");

    const methods = p.features?.methods || [];
    const events = p.features?.events || [];
    console.log(`\n  ${methods.length} methods advertised, ${events.length} events`);

    const need = ["chat.send", "chat.abort", "chat.history", "sessions.abort",
                  "tools.invoke", "sessions.list"];
    console.log("\n  --- methods this plan depends on ---");
    for (const m of need) {
      console.log(`   ${methods.includes(m) ? "OK  " : "MISS"}  ${m}`);
    }
    const needEv = ["chat", "session.message", "session.tool", "session.operation", "tick"];
    console.log("  --- events this plan depends on ---");
    for (const e of needEv) {
      console.log(`   ${events.includes(e) ? "OK  " : "MISS"}  ${e}`);
    }

    console.log("\n  --- all chat.* / session[s].* / tools.* methods ---");
    console.log("   " + methods.filter(m => /^(chat|sessions?|tools)\./.test(m)).join("\n   "));
    console.log("\n  --- all events ---");
    console.log("   " + events.join("\n   "));

    ws.close();
    return;
  }
});

ws.on("error", (e) => { console.log("socket error:", e.message); process.exit(1); });
ws.on("close", () => process.exit(0));
setTimeout(() => { console.log("timeout"); process.exit(1); }, 20000);
