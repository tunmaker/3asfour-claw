// Persistent operator connection to the OpenClaw gateway.
//
// Two things here are not obvious and both cost a debugging session to find:
// chat.send is asynchronous and answers with a runId, not a reply; and operator
// connections are broadcast, so every session's events arrive on this socket and
// must be filtered by runId or a concurrent turn bleeds into yours.
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { EventEmitter } from "node:events";

const require = createRequire("/home/openclaw/.npm-global/lib/node_modules/openclaw/");
const WebSocket = require("ws");

export function readToken(envFile) {
  if (process.env.OPENCLAW_GATEWAY_TOKEN) return process.env.OPENCLAW_GATEWAY_TOKEN;
  for (const line of readFileSync(envFile, "utf8").split("\n")) {
    const m = line.match(/^\s*OPENCLAW_GATEWAY_TOKEN=(.*)$/);
    if (m) return m[1].trim().replace(/^["']|["']$/g, "");
  }
  throw new Error(`no OPENCLAW_GATEWAY_TOKEN in env or ${envFile}`);
}

// A chat event's `message` is {role, content}, where content is a string or an
// array of parts. Pull plain text out of either shape.
export function messageText(m) {
  if (!m) return "";
  const c = m.content;
  if (typeof c === "string") return c;
  if (Array.isArray(c)) {
    return c.filter((p) => p && p.type === "text" && typeof p.text === "string")
            .map((p) => p.text).join("");
  }
  return "";
}

export class GatewayClient extends EventEmitter {
  constructor({ url, envFile, log = () => {}, scopes = ["operator.read", "operator.write"] }) {
    super();
    this.url = url;
    this.envFile = envFile;
    // cron.* and sessions.reset need operator.admin; the voice path does not,
    // and asking for it there would widen what a compromised turn could reach.
    this.scopes = scopes;
    this.log = log;
    this.ws = null;
    this.ready = false;
    this.nextId = 0;
    this.pending = new Map();
    this.subscribed = new Set();
    this.runs = new Map();          // runId -> run state
    this.reconnectDelay = 1000;
  }

  connect() {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.url);
      this.ws = ws;
      let settled = false;

      ws.on("message", (raw) => {
        let f;
        try { f = JSON.parse(raw.toString()); } catch { return; }

        if (f.type === "event" && f.event === "connect.challenge") {
          ws.send(JSON.stringify({
            type: "req", id: String(++this.nextId), method: "connect",
            params: {
              minProtocol: 4, maxProtocol: 4,
              client: { id: "gateway-client", version: "0.1.0", platform: "linux", mode: "backend" },
              role: "operator", scopes: this.scopes,
              caps: [], commands: [], permissions: {},
              auth: { token: readToken(this.envFile) },
              locale: "ar-TN", userAgent: "abbes-orchestrator/0.1.0",
            },
          }));
          return;
        }

        if (f.type === "res") {
          const p = this.pending.get(f.id);
          if (p) {
            this.pending.delete(f.id);
            f.ok ? p.res(f.payload) : p.rej(new Error(JSON.stringify(f.error)));
            return;
          }
          if (f.payload?.type === "hello-ok") {
            this.ready = true;
            this.reconnectDelay = 1000;
            this.subscribed.clear();
            this.log(`gateway: connected, protocol ${f.payload.protocol}`);
            if (!settled) { settled = true; resolve(f.payload); }
          } else if (f.ok === false && !settled) {
            settled = true;
            reject(new Error("connect rejected: " + JSON.stringify(f.error)));
          }
          return;
        }

        if (f.type === "event") this._onEvent(f);
      });

      ws.on("close", () => {
        this.ready = false;
        for (const r of this.runs.values()) r.fail?.(new Error("gateway connection closed"));
        this.runs.clear();
        this.log("gateway: disconnected, retrying");
        setTimeout(() => this.connect().catch(() => {}), this.reconnectDelay);
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
      });

      ws.on("error", (e) => {
        if (!settled) { settled = true; reject(e); }
        else this.log("gateway: socket error " + e.message);
      });

      setTimeout(() => {
        if (!settled) { settled = true; reject(new Error("connect timeout")); }
      }, 15000);
    });
  }

  call(method, params) {
    if (!this.ws || this.ws.readyState !== 1) {
      return Promise.reject(new Error("gateway not connected"));
    }
    const id = String(++this.nextId);
    return new Promise((res, rej) => {
      this.pending.set(id, { res, rej });
      this.ws.send(JSON.stringify({ type: "req", id, method, params }));
      setTimeout(() => {
        if (this.pending.delete(id)) rej(new Error(`${method} timed out`));
      }, 30000);
    });
  }

  _onEvent(f) {
    const pl = f.payload || {};
    // Broadcast: only events carrying one of our runIds are ours.
    const run = pl.runId ? this.runs.get(pl.runId) : null;
    if (!run) return;

    if (f.event === "chat") {
      if (typeof pl.deltaText === "string" && pl.deltaText.length) {
        if (pl.replace) run.onReplace(pl.deltaText);
        else run.onDelta(pl.deltaText);
      }
      const t = messageText(pl.message);
      if (t) run.lastMessage = t;
      if (pl.state === "final") run.finish(pl.stopReason || "stop");
    } else if (f.event === "session.tool") {
      const phase = pl.data?.phase;
      const name = pl.data?.name;
      if (phase === "start") run.onToolStart(name);
    }
  }

  /**
   * Subscribe to session events for this connection.
   *
   * Since 2026.8.1 the parameters are `sessions.list`'s, and they only select an
   * initial snapshot -- they do not filter which events arrive. Passing the old
   * `{ sessionKey }` is now rejected outright:
   *   "invalid sessions.subscribe params: unexpected property 'sessionKey'"
   * So `{}` it is, which subscribes and asks for no snapshot.
   *
   * The subscription was never per-session anyway. An operator connection has
   * always received events for every session, which is why every consumer here
   * filters on runId; the key argument only ever looked like it narrowed things.
   */
  async subscribe(sessionKey) {
    if (this.subscribed.has("*")) return;
    await this.call("sessions.subscribe", {});
    this.subscribed.add("*");
  }

  /**
   * Send a turn and stream it. Calls handlers as text arrives; resolves with the
   * full reply when the run reaches its final state.
   */
  async sendTurn(sessionKey, message, { onDelta, onToolStart, timeoutMs = 180000 } = {}) {
    await this.subscribe(sessionKey);

    let resolveRun, rejectRun;
    const done = new Promise((res, rej) => { resolveRun = res; rejectRun = rej; });

    const started = Date.now();
    const run = {
      text: "", lastMessage: "", firstDeltaAt: null, tools: [],
      onDelta: (d) => {
        if (run.firstDeltaAt === null) run.firstDeltaAt = Date.now() - started;
        run.text += d;
        onDelta?.(d, run.text);
      },
      onReplace: (d) => {
        if (run.firstDeltaAt === null) run.firstDeltaAt = Date.now() - started;
        run.text = d;
        onDelta?.(d, run.text, true);
      },
      onToolStart: (name) => { run.tools.push({ name, at: Date.now() - started }); onToolStart?.(name); },
      finish: (stopReason) => {
        // A run can end with no deltas at all. Fall back to the cumulative
        // snapshot so a silent stream still yields the reply.
        const text = run.text || run.lastMessage || "";
        resolveRun({ text, stopReason, tools: run.tools,
                     firstDeltaMs: run.firstDeltaAt, totalMs: Date.now() - started });
      },
      fail: (e) => rejectRun(e),
    };

    const idempotencyKey = randomUUID();
    const res = await this.call("chat.send", { sessionKey, message, idempotencyKey });
    if (!res?.runId) throw new Error("chat.send returned no runId: " + JSON.stringify(res));
    this.runs.set(res.runId, run);

    const timer = setTimeout(() => run.fail(new Error("turn timed out")), timeoutMs);
    try {
      return await done;
    } finally {
      clearTimeout(timer);
      this.runs.delete(res.runId);
    }
  }

  abort(sessionKey) {
    return this.call("chat.abort", { sessionKey }).catch(() => {});
  }
}
