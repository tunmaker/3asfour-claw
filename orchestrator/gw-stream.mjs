// Phase 1.2 — send a turn over the gateway WebSocket and prove the delta stream.
// Verifies: concatenated deltaText == final cumulative message, and reports the
// offset of the first delta (the real floor for time-to-first-audio).
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
const require = createRequire("/home/openclaw/.npm-global/lib/node_modules/openclaw/");
const WebSocket = require("ws");

const URL = process.env.GW_URL || "ws://127.0.0.1:18789";
const ENV = process.env.OPENCLAW_ENV || `${process.env.HOME}/.openclaw/openclaw.env`;
const SESSION = process.env.ABBES_SESSION_KEY || "wsprobe";
const MESSAGE = process.argv[2] || "قداش الوقت؟";

function token() {
  if (process.env.OPENCLAW_GATEWAY_TOKEN) return process.env.OPENCLAW_GATEWAY_TOKEN;
  for (const line of readFileSync(ENV, "utf8").split("\n")) {
    const m = line.match(/^\s*OPENCLAW_GATEWAY_TOKEN=(.*)$/);
    if (m) return m[1].trim().replace(/^["']|["']$/g, "");
  }
  throw new Error("no OPENCLAW_GATEWAY_TOKEN");
}

const ws = new WebSocket(URL);
let id = 0;
const next = () => String(++id);
const pending = new Map();
function call(method, params) {
  const rid = next();
  return new Promise((res, rej) => {
    pending.set(rid, { res, rej });
    ws.send(JSON.stringify({ type: "req", id: rid, method, params }));
  });
}

let deltas = [];          // every deltaText increment, in order
let lastMessage = "";     // cumulative snapshot the gateway reports
let replaceCount = 0;
let toolEvents = [];
let tSend = 0, tFirstDelta = 0;

// A chat event's `message` is an object: {role, content} where content is a string
// or an array of parts. Pull the plain text out of either shape.
function msgText(m) {
  if (!m) return "";
  const c = m.content;
  if (typeof c === "string") return c;
  if (Array.isArray(c)) {
    return c.filter(p => p && p.type === "text" && typeof p.text === "string")
            .map(p => p.text).join("");
  }
  return "";
}

let done = false;
let runId = null, sendResult = null;

ws.on("open", () => {});

ws.on("message", async (raw) => {
  let f;
  try { f = JSON.parse(raw.toString()); } catch { return; }

  if (f.type === "event" && f.event === "connect.challenge") {
    ws.send(JSON.stringify({
      type: "req", id: next(), method: "connect",
      params: {
        minProtocol: 4, maxProtocol: 4,
        client: { id: "gateway-client", version: "0.1.0", platform: "linux", mode: "backend" },
        role: "operator", scopes: ["operator.read", "operator.write"],
        caps: [], commands: [], permissions: {},
        auth: { token: token() }, locale: "ar-TN",
        userAgent: "abbes-orchestrator/0.1.0",
      },
    }));
    return;
  }

  if (f.type === "res") {
    const p = pending.get(f.id);
    if (p) { pending.delete(f.id); f.ok ? p.res(f.payload) : p.rej(f.error); return; }
    if (f.ok && f.payload?.type === "hello-ok") {
      try {
        const sub = await call("sessions.subscribe", { sessionKey: SESSION });
        console.log("  subscribe ok:", JSON.stringify(sub).slice(0, 200));
      } catch (e) { console.log("  subscribe REFUSED:", JSON.stringify(e)); }
      console.log(`> ${MESSAGE}`);
      tSend = Date.now();
      call("chat.send", {
        sessionKey: SESSION,
        message: MESSAGE,
        idempotencyKey: randomUUID(),
      }).then((r) => {
        console.log("  chat.send returned:", JSON.stringify(r).slice(0, 200));
        runId = r?.runId;
        sendResult = r;
      }).catch((e) => { console.log("chat.send failed:", JSON.stringify(e)); process.exit(1); });
    }
    return;
  }

  if (f.type !== "event") return;
  const pl = f.payload || {};
  if (process.env.DEBUG_EVENTS) {
    console.log("  [ev]", f.event, JSON.stringify(pl).slice(0, 160));
  }

  if (f.event === "chat") {
    // Operator connections are broadcast: chat events arrive for EVERY session,
    // not just the one we sent to. Without this filter a concurrent turn (the
    // voice loop, a heartbeat) bleeds its deltas into ours.
    if (!runId || pl.runId !== runId) return;
    if (typeof pl.deltaText === "string" && pl.deltaText.length) {
      if (!tFirstDelta) tFirstDelta = Date.now();
      if (pl.replace) { replaceCount++; deltas = [pl.deltaText]; }
      else deltas.push(pl.deltaText);
      process.stdout.write(".");
    }
    const t = msgText(pl.message);
    if (t) lastMessage = t;
    if (pl.state === "final") setTimeout(() => report(sendResult), 500);
  }
  if (f.event === "session.tool") {
    if (!runId || pl.runId !== runId) return;
    toolEvents.push({ at: Date.now() - tSend, payload: JSON.stringify(pl).slice(0, 120) });
  }
});

function report(sendResult) {
  if (done) return; done = true;
  const joined = deltas.join("");
  const final = lastMessage || (sendResult?.reply ?? "");
  console.log("\n");
  console.log("  first delta at   :", tFirstDelta ? (tFirstDelta - tSend) + " ms" : "NONE RECEIVED");
  console.log("  total turn       :", (Date.now() - tSend - 500) + " ms");
  console.log("  delta count      :", deltas.length, replaceCount ? `(${replaceCount} replace)` : "");
  console.log("  session.tool     :", toolEvents.length, toolEvents.map(t => t.at + "ms").join(" "));
  console.log("  joined deltas    :", JSON.stringify(joined.slice(0, 120)));
  console.log("  final message    :", JSON.stringify(final.slice(0, 120)));
  console.log("  MATCH            :", joined.trim() === final.trim() ? "YES" : "NO");
  if (joined.trim() !== final.trim()) {
    console.log("    joined len", joined.length, "final len", final.length);
  }
  ws.close();
  process.exit(0);
}

ws.on("error", (e) => { console.log("socket error:", e.message); process.exit(1); });
setTimeout(() => { console.log("\n(window closed)"); report(sendResult); }, 60000);
