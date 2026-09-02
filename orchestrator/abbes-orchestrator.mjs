// The streaming voice path, owned in one place.
//
// The Pi used to orchestrate: POST audio to Vosk, SSH to the gateway, POST text
// to Piper, play the file. Four round trips it had to sequence itself on a
// Cortex-A53 with 327 MB free. Here it makes one request and gets audio back.
//
//   POST /turn        WAV in -> WAV out. Blocking, same shape as before.
//   POST /turn/stream WAV in -> WAV chunks out, one per sentence, as they render.
//   GET  /announce/stream  Held open by the Pi. Speech Abbes was not asked for.
//   POST /announce         Text in, spoken on the open stream. Cron delivers here.
//   GET  /health
//
// Phase 2.1 is /turn. Phase 2.2 is /turn/stream. Both share one pipeline so the
// only difference is when bytes leave.
//
// The announce pair is the other direction, and it is the only way Abbes speaks
// without being spoken to. Everything that wants to interrupt the household goes
// through one door, so the quiet-hours veto and the never-talk-over-a-turn rule
// live in one place instead of in every caller.

import http from "node:http";
import { readFileSync } from "node:fs";
import { GatewayClient } from "./gateway-client.mjs";
import { Chunker } from "./sentences.mjs";
import { QuietHours } from "./quiet.mjs";
import { VisionGate } from "./vision.mjs";

const PORT        = +(process.env.ABBES_ORCH_PORT || 18790);
const GW_URL      = process.env.GW_URL      || "ws://127.0.0.1:18789";
const ENV_FILE    = process.env.OPENCLAW_ENV || `${process.env.HOME}/.openclaw/openclaw.env`;
const STT_URL     = process.env.STT_URL     || required("STT_URL");
const TTS_URL     = process.env.TTS_URL     || required("TTS_URL");
const SESSION_KEY = process.env.ABBES_SESSION_KEY || "voice";
const VOICE       = process.env.PIPER_VOICE || "ar_JO-kareem-medium";
const STT_TIMEOUT = +(process.env.STT_TIMEOUT_MS || 60000);
const TTS_TIMEOUT = +(process.env.TTS_TIMEOUT_MS || 15000);

function required(name) {
  console.error(`[orchestrator] ${name} is not set`);
  process.exit(2);
}

const ANNOUNCE_WAIT = +(process.env.ANNOUNCE_WAIT_MS || 45000);
const CAPTION_URL   = process.env.CAPTION_URL || "";
// Off by default. The gate can watch and describe the room from the moment it is
// deployed; deciding to say something unprompted about what it saw is a separate
// judgement, and one that should be switched on deliberately rather than
// arriving with a deploy.
const VISION_TRIGGER = process.env.VISION_TRIGGER_ENABLED === "1";
const GW_HTTP       = process.env.GW_HTTP || GW_URL.replace(/^ws/, "http");
const QWEN_VISION_URL = process.env.VISION_QWEN_URL || "";
const LLAMACPP_KEY    = process.env.LLAMACPP_API_KEY || "";

const log = (...a) => console.log(`[${new Date().toISOString().slice(11, 23)}]`, ...a);

const quiet = new QuietHours({ envFile: ENV_FILE, log });

// ---------------------------------------------------------------- speech in

async function transcribe(wav) {
  const form = new FormData();
  form.append("file", new Blob([wav], { type: "audio/wav" }), "turn.wav");
  form.append("language", "ar");
  form.append("response_format", "json");
  const res = await fetch(STT_URL, {
    method: "POST", body: form, signal: AbortSignal.timeout(STT_TIMEOUT),
  });
  if (!res.ok) throw new Error(`stt ${res.status}`);
  const d = await res.json();
  if (d.error) throw new Error(`stt: ${d.error}`);
  return (d.text || "").trim();
}

// --------------------------------------------------------------- speech out

async function synthesize(text) {
  const res = await fetch(TTS_URL, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text, voice: VOICE }),
    signal: AbortSignal.timeout(TTS_TIMEOUT),
  });
  if (!res.ok) throw new Error(`tts ${res.status}`);
  return Buffer.from(await res.arrayBuffer());
}

// Piper returns a complete RIFF file per sentence. Concatenating files would put
// a 44-byte header in the middle of the audio, which is an audible click, so the
// header is taken from the first part and the rest contribute data only.
function wavBody(buf) {
  if (buf.length < 12 || buf.toString("ascii", 0, 4) !== "RIFF") return buf;
  let off = 12;
  while (off + 8 <= buf.length) {
    const id = buf.toString("ascii", off, off + 4);
    const size = buf.readUInt32LE(off + 4);
    if (id === "data") return buf.subarray(off + 8, Math.min(off + 8 + size, buf.length));
    off += 8 + size + (size & 1);
  }
  return buf.subarray(44);
}

function wavHeader(dataLen, { sampleRate = 22050, channels = 1, bits = 16 } = {}) {
  const h = Buffer.alloc(44);
  const byteRate = sampleRate * channels * (bits / 8);
  h.write("RIFF", 0); h.writeUInt32LE(36 + dataLen, 4); h.write("WAVE", 8);
  h.write("fmt ", 12); h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20);
  h.writeUInt16LE(channels, 22); h.writeUInt32LE(sampleRate, 24);
  h.writeUInt32LE(byteRate, 28); h.writeUInt16LE(channels * (bits / 8), 32);
  h.writeUInt16LE(bits, 34); h.write("data", 36); h.writeUInt32LE(dataLen, 40);
  return h;
}

function wavFormat(buf) {
  try {
    return { sampleRate: buf.readUInt32LE(24), channels: buf.readUInt16LE(22),
             bits: buf.readUInt16LE(34) };
  } catch { return {}; }
}

// The Pi used to strip the wake word before sending, because it did its own STT.
// Now STT is here, so the stripping is here too — the model should not be asked
// "يا عباس، قداش الوقت", it should be asked "قداش الوقت". Fold the same forms the
// wake matcher folds, so عبّاس, عباس and Abbes all strip.
function foldArabic(t) {
  return t
    .replace(/[\u064B-\u0652\u0670]/g, "")   // harakat
    .replace(/[أإآٱ]/g, "ا").replace(/ى/g, "ي").replace(/ة/g, "ه")
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function stripTrigger(text, words) {
  if (!words?.length) return text;
  const set = new Set(words.map((w) => foldArabic(w.trim())).filter(Boolean));
  // Work token-wise. Folding changes length (عبّاس -> عباس), so slicing the
  // original by a folded length cuts in the wrong place.
  const tokens = text.trim().split(/\s+/);
  let i = 0;
  while (i < tokens.length) {
    const bare = foldArabic(tokens[i]).replace(/^[\s,،.!؟:]+|[\s,،.!؟:]+$/g, "");
    if (!set.has(bare)) break;
    i++;
  }
  const rest = tokens.slice(i).join(" ").replace(/^[\s,،.]+/, "");
  return rest || text;   // the bare name alone is a turn in its own right
}

// ------------------------------------------------------------------ the turn

const gw = new GatewayClient({ url: GW_URL, envFile: ENV_FILE, log });

/**
 * One turn, start to finish. `onAudio(buf, meta)` is called per sentence as soon
 * as that sentence is rendered; the caller decides whether to forward it now
 * (streaming) or collect it (blocking).
 */
async function runTurn(wav, { onAudio, onTranscript, triggerWords } = {}) {
  const t0 = Date.now();
  const marks = {};

  const heard = await transcribe(wav);
  const transcript = stripTrigger(heard, triggerWords);
  marks.sttMs = Date.now() - t0;
  if (transcript !== heard) log(`  stripped trigger: ${JSON.stringify(heard)} -> ${JSON.stringify(transcript)}`);
  onTranscript?.(transcript);
  if (!transcript) return { transcript: "", reply: "", marks, empty: true };

  const chunker = new Chunker();
  let queue = Promise.resolve();
  let index = 0;
  const speak = (sentence) => {
    queue = queue.then(async () => {
      const at = Date.now() - t0;
      const audio = await synthesize(sentence);
      const meta = { index: index++, sentence, requestedAt: at, readyAt: Date.now() - t0 };
      if (marks.firstAudioMs === undefined) marks.firstAudioMs = meta.readyAt;
      await onAudio?.(audio, meta);
    }).catch((e) => log("tts failed:", e.message));
  };

  const turn = await gw.sendTurn(SESSION_KEY, transcript, {
    onDelta: (_d, _full, replaced) => {
      if (replaced) { chunker.replace(_full); return; }
      for (const s of chunker.push(_d)) speak(s);
    },
    onToolStart: (name) => log(`  tool: ${name}`),
  });

  for (const s of chunker.end()) speak(s);
  await queue;

  marks.firstDeltaMs = turn.firstDeltaMs;
  marks.replyDoneMs = turn.totalMs + marks.sttMs;
  marks.totalMs = Date.now() - t0;
  return { transcript, reply: turn.text, tools: turn.tools, marks };
}

// ----------------------------------------------------------------- announce

// Same framing as /turn/stream -- one byte of kind, four of big-endian length --
// so the Pi reuses its reader. Downlink kinds are 0x8x to keep them distinct in
// a log from the uplink kinds a turn uses.
const F_SPEECH = 0x81, F_SPEECH_END = 0x82, F_CONTROL = 0x83;

function writeFrame(res, kind, body) {
  const h = Buffer.alloc(5);
  h.writeUInt8(kind, 0);
  h.writeUInt32BE(body.length, 1);
  return res.write(Buffer.concat([h, body]));
}

const listeners = new Set();

// A silent connection is indistinguishable from a dead one at both ends. The Pi
// gives up after its read timeout and reconnects, but the socket it abandoned
// stays in this set until something writes to it -- so the count climbed one per
// reconnect, and announcements were being written to sockets nobody was reading.
// A ping proves the link in both directions and gives us a write that fails.
const PING_MS = +(process.env.ANNOUNCE_PING_MS || 30000);
setInterval(() => {
  const ping = Buffer.from(JSON.stringify({ type: "ping", at: Date.now() }));
  for (const res of [...listeners]) {
    let alive = false;
    try { alive = writeFrame(res, F_CONTROL, ping) !== undefined && !res.destroyed; }
    catch { alive = false; }
    if (!alive) {
      listeners.delete(res);
      log(`announce listener dropped on a failed ping (${listeners.size} left)`);
      try { res.end(); } catch { /* already gone */ }
    }
  }
}, PING_MS).unref();

// A turn already owns the speaker. Announcing into one would talk over Abbes
// answering a question, which is worse than being late.
let turnsInFlight = 0;
const idle = [];
function turnStarted() { turnsInFlight++; }
function turnEnded() {
  turnsInFlight = Math.max(0, turnsInFlight - 1);
  if (turnsInFlight === 0) while (idle.length) idle.shift()();
}
function whenIdle(timeoutMs) {
  if (turnsInFlight === 0) return Promise.resolve(true);
  return new Promise((resolve) => {
    const done = (v) => { clearTimeout(timer); const i = idle.indexOf(fn); if (i >= 0) idle.splice(i, 1); resolve(v); };
    const fn = () => done(true);
    const timer = setTimeout(() => done(false), timeoutMs);
    idle.push(fn);
  });
}

// Captioning costs GPU that a voice turn is also using, so the gate is told to
// stand down while one is in flight rather than racing it.
const vision = CAPTION_URL
  ? new VisionGate({ captionUrl: CAPTION_URL, log, isBusy: () => turnsInFlight > 0 })
  : null;

// One announcement at a time, in order. Two overlapping ones would interleave
// their sentences on the same playback stream and be unintelligible.
let announceQueue = Promise.resolve();

/**
 * Speak text nobody asked for. Returns why it did not happen, or null on success.
 * Every refusal is a normal outcome and is logged, not thrown.
 */
function announce(text, { source = "unknown" } = {}) {
  const job = announceQueue.then(async () => {
    const clean = String(text || "").trim();
    if (!clean) return { skipped: "empty" };
    if (quiet.blocks(source)) {
      log(`announce refused (quiet hours) from ${source}: ${JSON.stringify(clean.slice(0, 60))}`);
      return { skipped: "quiet-hours" };
    }
    if (listeners.size === 0) {
      log(`announce dropped (nobody listening) from ${source}`);
      return { skipped: "no-listener" };
    }
    if (!(await whenIdle(ANNOUNCE_WAIT))) {
      log(`announce dropped (a turn held the speaker for ${ANNOUNCE_WAIT}ms) from ${source}`);
      return { skipped: "busy" };
    }
    // Re-check: the wait above can cross into the quiet window.
    if (quiet.blocks(source)) {
      log(`announce refused (quiet hours, after waiting) from ${source}`);
      return { skipped: "quiet-hours" };
    }

    const t0 = Date.now();
    const chunker = new Chunker();
    let spoken = 0;
    for (const sentence of [...chunker.push(clean), ...chunker.end()]) {
      const audio = await synthesize(sentence);
      for (const res of listeners) writeFrame(res, F_SPEECH, audio);
      spoken++;
    }
    for (const res of listeners) writeFrame(res, F_SPEECH_END, Buffer.from(JSON.stringify({ text: clean })));
    log(`announce from ${source}: ${spoken} sentence(s), ${Date.now() - t0}ms, ${listeners.size} listener(s)`);
    return { spoken, ms: Date.now() - t0 };
  }).catch((e) => {
    log("announce failed:", e.message);
    return { skipped: "error", error: e.message };
  });
  announceQueue = job.then(() => {}, () => {});
  return job;
}

/**
 * What a changed scene does.
 *
 * Not announced directly. Unlike a prayer time, "the room changed" carries no
 * sentence with it -- whether it is worth saying anything is a judgement, and
 * that is the one job worth spending a model turn on. It goes to the autonomy
 * session, never the voice session, and whatever comes back reaches the room
 * only through the same announce lane as everything else, with the same veto.
 */
async function onSceneChange({ present, caption }) {
  const token = readHookToken();
  if (!token) { log("vision: scene changed but no hook token; not escalating"); return; }
  const body = {
    message:
      `[vision] ${present ? "Someone has come into the room." : "The room is now empty."}\n` +
      `What the camera sees: ${caption || "no description available"}\n` +
      `If this is worth telling the household right now, reply with one short ` +
      `sentence in Modern Standard Arabic and nothing else. If it is not, reply exactly NO_REPLY.`,
    sessionKey: "autonomy",
    name: "vision",
    model: "llamacpp/qwen3.5-9b-q8-auto",
    deliver: false,
  };
  try {
    const res = await fetch(`${GW_HTTP}/hooks/agent`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(120000),
    });
    if (!res.ok) { log(`vision: hook returned ${res.status}`); return; }
    const out = await res.json().catch(() => ({}));
    const said = String(out.reply ?? out.text ?? out.result?.reply ?? "").trim();
    if (!said || /NO_REPLY/i.test(said)) { log("vision: model chose to stay quiet"); return; }
    await announce(said, { source: "vision" });
  } catch (e) {
    log(`vision: escalation failed (${e.message})`);
  }
}

/**
 * Ask Qwen about a frame, on the slot reserved for image prefills.
 *
 * id_slot keeps a 1024-token image out of the voice session's slot, which would
 * otherwise cost that session its cached prefix and turn a 0.09s prefill into
 * a 9s one on the next thing anybody says out loud. Slot 1 is the shared
 * everything-but-voice slot; evicting main's prefix is an accepted cost there.
 */
async function askQwenAboutImage(jpeg, prompt) {
  if (!QWEN_VISION_URL) throw new Error("VISION_QWEN_URL is not set");
  const res = await fetch(QWEN_VISION_URL, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(LLAMACPP_KEY ? { authorization: `Bearer ${LLAMACPP_KEY}` } : {}),
    },
    body: JSON.stringify({
      model: "qwen3.5-9b-q8-vision",
      id_slot: 1,
      messages: [{
        role: "user",
        content: [
          { type: "image_url", image_url: { url: `data:image/jpeg;base64,${jpeg.toString("base64")}` } },
          { type: "text", text: prompt },
        ],
      }],
      max_tokens: 200,
      temperature: 0.3,
    }),
    signal: AbortSignal.timeout(120000),
  });
  if (!res.ok) throw new Error(`qwen vision ${res.status}`);
  const d = await res.json();
  return (d.choices?.[0]?.message?.content || "").trim();
}

function readHookToken() {
  try {
    for (const line of readFileSync(ENV_FILE, "utf8").split("\n")) {
      const m = line.match(/^\s*OPENCLAW_HOOK_TOKEN\s*=\s*(.*)$/);
      if (m) return m[1].trim().replace(/^["']|["']$/g, "");
    }
  } catch { /* nothing to read: escalation is simply unavailable */ }
  return null;
}

// Cron's webhook delivery and a hand-rolled curl do not agree on where the text
// lives, so accept the shapes we actually see and say so when we cannot find it.
function announceText(body) {
  if (typeof body === "string") return body;
  if (!body || typeof body !== "object") return null;
  for (const k of ["text", "message", "reply", "notificationText", "content"]) {
    if (typeof body[k] === "string" && body[k].trim()) return body[k];
  }
  for (const k of ["result", "payload", "data", "run"]) {
    if (body[k] && typeof body[k] === "object") {
      const nested = announceText(body[k]);
      if (nested) return nested;
    }
  }
  return null;
}

// -------------------------------------------------------------------- server

async function readBody(req, limit = 32 * 1024 * 1024) {
  const parts = [];
  let n = 0;
  for await (const c of req) {
    n += c.length;
    if (n > limit) throw new Error("body too large");
    parts.push(c);
  }
  return Buffer.concat(parts);
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");

  if (req.method === "GET" && url.pathname === "/health") {
    const win = quiet.window();
    res.writeHead(gw.ready ? 200 : 503, { "content-type": "application/json" });
    res.end(JSON.stringify({
      ok: gw.ready,
      gateway: gw.ready ? "connected" : "down",
      listeners: listeners.size,
      turnsInFlight,
      quietHours: win ? win.spec : null,
      quietNow: quiet.blocks(),
      quietExempt: [...quiet.exempt()],
      vision: vision ? { trigger: VISION_TRIGGER, ...vision.snapshot() } : null,
    }));
    return;
  }

  // Held open by the Pi for the life of its process. Nothing is written until
  // there is something to say, so an idle household costs one open socket.
  if (req.method === "GET" && url.pathname === "/announce/stream") {
    res.writeHead(200, {
      "content-type": "application/octet-stream",
      "cache-control": "no-store",
      "x-abbes-announce": "1",
    });
    listeners.add(res);
    log(`announce listener attached (${listeners.size} total)`);
    writeFrame(res, F_CONTROL, Buffer.from(JSON.stringify({ type: "hello", quietHours: quiet.window()?.spec ?? null })));
    const drop = () => {
      if (listeners.delete(res)) log(`announce listener gone (${listeners.size} left)`);
    };
    req.on("close", drop);
    req.on("error", drop);
    res.on("error", drop);
    return;
  }

  // One frame from the Pi's camera poll. Answers immediately with what the gate
  // decided, so the Pi can log it without holding any state of its own.
  if (req.method === "POST" && url.pathname === "/vision/frame") {
    if (!vision) { res.writeHead(503, { "content-type": "application/json" }); res.end(JSON.stringify({ error: "CAPTION_URL not set" })); return; }
    let jpeg;
    try { jpeg = await readBody(req, 4 * 1024 * 1024); }
    catch (e) { res.writeHead(413).end(e.message); return; }
    const changed = await vision.offer(jpeg);
    if (changed && VISION_TRIGGER) await onSceneChange(changed);
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ changed: Boolean(changed), ...(changed || {}) }));
    return;
  }

  // "Take a picture and tell me what you see." The Pi polls every few seconds,
  // so the newest frame is a few seconds old at worst -- fresh enough that
  // asking it to grab another would add latency for nothing.
  if (req.method === "POST" && url.pathname === "/vision/look") {
    if (!vision) { res.writeHead(503, { "content-type": "application/json" }); res.end(JSON.stringify({ error: "vision is not configured" })); return; }
    if (!vision.lastFrame) { res.writeHead(503, { "content-type": "application/json" }); res.end(JSON.stringify({ error: "no frame yet; is the camera running?" })); return; }

    let body = {};
    try { body = JSON.parse((await readBody(req, 64 * 1024)).toString("utf8") || "{}"); } catch { /* defaults */ }
    const prompt = String(body.prompt || "Describe what you see in this image.").slice(0, 500);
    const t0 = Date.now();
    try {
      // The 256M captioner is for the gate, where the question is closed and the
      // cost is paid every few seconds. A person asking what the camera sees
      // deserves the model that can actually answer, on its own pinned slot so
      // the image prefill cannot evict the voice session's prefix.
      const answer = body.quick
        ? await vision.caption(vision.lastFrame, prompt, { maxTokens: 80 })
        : await askQwenAboutImage(vision.lastFrame, prompt);
      log(`vision/look (${body.quick ? "small" : "qwen"}) ${Date.now() - t0}ms: ${answer.slice(0, 80)}`);
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ answer, ms: Date.now() - t0, model: body.quick ? "smolvlm" : "qwen" }));
    } catch (e) {
      log(`vision/look failed: ${e.message}`);
      res.writeHead(502, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: e.message }));
    }
    return;
  }

  if (req.method === "GET" && url.pathname === "/vision/state") {
    res.writeHead(vision ? 200 : 503, { "content-type": "application/json" });
    res.end(JSON.stringify(vision ? vision.snapshot() : { error: "CAPTION_URL not set" }));
    return;
  }

  if (req.method === "POST" && url.pathname === "/announce") {
    let body;
    try { body = JSON.parse((await readBody(req, 256 * 1024)).toString("utf8") || "{}"); }
    catch (e) { res.writeHead(400, { "content-type": "application/json" }).end(JSON.stringify({ error: "bad json: " + e.message })); return; }

    const text = announceText(body);
    if (!text) {
      log("announce: no text found in payload, keys:", Object.keys(body || {}).join(","));
      res.writeHead(400, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "no text in payload", sawKeys: Object.keys(body || {}) }));
      return;
    }
    // Query param first: cron's webhook delivery controls the URL but not the
    // body, so ?source=cron:abbes-prayer is the only way a job can name itself
    // -- and naming itself is what lets QUIET_HOURS_EXEMPT single it out.
    const source = String(url.searchParams.get("source") || body.source ||
                          req.headers["x-abbes-source"] || "http");
    const out = await announce(text, { source });
    res.writeHead(out.skipped ? 202 : 200, { "content-type": "application/json" });
    res.end(JSON.stringify({ ok: !out.skipped, ...out }));
    return;
  }

  const streaming = url.pathname === "/turn/stream";
  if (req.method !== "POST" || (url.pathname !== "/turn" && !streaming)) {
    res.writeHead(404).end("not found");
    return;
  }

  // Percent-encoded by the client: HTTP headers are latin-1 and these are Arabic.
  let triggerWords = [];
  try {
    triggerWords = decodeURIComponent(req.headers["x-abbes-trigger-words"] || "")
      .split(",").map((w) => w.trim()).filter(Boolean);
  } catch { triggerWords = []; }

  let wav;
  try { wav = await readBody(req); }
  catch (e) { res.writeHead(413).end(e.message); return; }

  turnStarted();
  try {
    if (!streaming) {
      // Phase 2.1: collect everything, answer with one WAV. Same shape as before.
      const bodies = [];
      let fmt = null;
      const out = await runTurn(wav, {
        triggerWords,
        onAudio: (buf) => { if (!fmt) fmt = wavFormat(buf); bodies.push(wavBody(buf)); },
      });
      const data = Buffer.concat(bodies);
      const file = data.length ? Buffer.concat([wavHeader(data.length, fmt), data]) : Buffer.alloc(0);
      log(`turn: "${out.transcript}" -> ${out.reply.length}c  ` +
          `stt ${out.marks.sttMs}ms  delta1 ${out.marks.firstDeltaMs}ms  ` +
          `audio1 ${out.marks.firstAudioMs}ms  total ${out.marks.totalMs}ms`);
      res.writeHead(200, {
        "content-type": "audio/wav",
        "x-abbes-transcript": encodeURIComponent(out.transcript),
        "x-abbes-reply": encodeURIComponent(out.reply),
        "x-abbes-marks": JSON.stringify(out.marks),
      });
      res.end(file);
      return;
    }

    // Phase 2.2: one chunk per sentence, sent the moment it renders.
    // Length-prefixed frames so the client can play each without waiting.
    res.writeHead(200, { "content-type": "application/octet-stream",
                         "cache-control": "no-store", "x-abbes-stream": "1" });
    const out = await runTurn(wav, {
      triggerWords,
      onTranscript: (t) => {
        const j = Buffer.from(JSON.stringify({ type: "transcript", text: t }));
        const h = Buffer.alloc(5); h.writeUInt8(1, 0); h.writeUInt32BE(j.length, 1);
        res.write(Buffer.concat([h, j]));
      },
      onAudio: (buf, meta) => new Promise((resolve) => {
        const h = Buffer.alloc(5); h.writeUInt8(2, 0); h.writeUInt32BE(buf.length, 1);
        log(`  sentence ${meta.index} ready at ${meta.readyAt}ms (${buf.length}b)`);
        res.write(Buffer.concat([h, buf]), () => resolve());
      }),
    });
    const j = Buffer.from(JSON.stringify({ type: "end", reply: out.reply, marks: out.marks }));
    const h = Buffer.alloc(5); h.writeUInt8(3, 0); h.writeUInt32BE(j.length, 1);
    res.end(Buffer.concat([h, j]));
    log(`stream: "${out.transcript}" delta1 ${out.marks.firstDeltaMs}ms ` +
        `audio1 ${out.marks.firstAudioMs}ms total ${out.marks.totalMs}ms`);
  } catch (e) {
    log("turn failed:", e.message);
    if (!res.headersSent) res.writeHead(502, { "content-type": "text/plain" });
    res.end("turn failed: " + e.message);
  } finally {
    turnEnded();
  }
});

// Node builds its HTTP stack lazily: the first fetch of the process paid 2.4s on
// a call that takes 180ms warm. Spend it at startup instead of on the first turn.
async function warmup() {
  const t = Date.now();
  const silence = Buffer.concat([wavHeader(3200, { sampleRate: 16000 }), Buffer.alloc(3200)]);
  await Promise.allSettled([
    transcribe(silence),
    synthesize("."),
  ]);
  log(`warmed http stack in ${Date.now() - t}ms`);
}

// The default model moved to the shared slot-1 lane; the voice session is the
// one thing that must stay on slot 0, so pin its model explicitly. sessions.patch
// persists on the session entry and survives gateway restarts, but not a session
// reset, hence on every orchestrator start rather than once ever.
async function pinVoiceModel() {
  try {
    await gw.call("sessions.patch", { key: SESSION_KEY, model: "llamacpp/qwen3.5-9b-q8" });
    log("voice session pinned to llamacpp/qwen3.5-9b-q8 (slot 0)");
  } catch (e) {
    log("could not pin the voice model:", e.message);
  }
}

gw.connect()
  .then(pinVoiceModel)
  .then(warmup)
  .then(() => server.listen(PORT, "127.0.0.1",
        () => log(`orchestrator listening on 127.0.0.1:${PORT}, session "${SESSION_KEY}"`)))
  .catch((e) => { log("cannot reach gateway:", e.message); process.exit(1); });

for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => { log("shutting down"); server.close(); process.exit(0); });
}
