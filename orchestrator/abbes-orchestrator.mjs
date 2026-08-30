// The streaming voice path, owned in one place.
//
// The Pi used to orchestrate: POST audio to Vosk, SSH to the gateway, POST text
// to Piper, play the file. Four round trips it had to sequence itself on a
// Cortex-A53 with 327 MB free. Here it makes one request and gets audio back.
//
//   POST /turn        WAV in -> WAV out. Blocking, same shape as before.
//   POST /turn/stream WAV in -> WAV chunks out, one per sentence, as they render.
//   GET  /health
//
// Phase 2.1 is /turn. Phase 2.2 is /turn/stream. Both share one pipeline so the
// only difference is when bytes leave.

import http from "node:http";
import { GatewayClient } from "./gateway-client.mjs";
import { Chunker } from "./sentences.mjs";

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

const log = (...a) => console.log(`[${new Date().toISOString().slice(11, 23)}]`, ...a);

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

// ------------------------------------------------------------------ the turn

const gw = new GatewayClient({ url: GW_URL, envFile: ENV_FILE, log });

/**
 * One turn, start to finish. `onAudio(buf, meta)` is called per sentence as soon
 * as that sentence is rendered; the caller decides whether to forward it now
 * (streaming) or collect it (blocking).
 */
async function runTurn(wav, { onAudio, onTranscript } = {}) {
  const t0 = Date.now();
  const marks = {};

  const transcript = await transcribe(wav);
  marks.sttMs = Date.now() - t0;
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
    res.writeHead(gw.ready ? 200 : 503, { "content-type": "application/json" });
    res.end(JSON.stringify({ ok: gw.ready, gateway: gw.ready ? "connected" : "down" }));
    return;
  }

  const streaming = url.pathname === "/turn/stream";
  if (req.method !== "POST" || (url.pathname !== "/turn" && !streaming)) {
    res.writeHead(404).end("not found");
    return;
  }

  let wav;
  try { wav = await readBody(req); }
  catch (e) { res.writeHead(413).end(e.message); return; }

  try {
    if (!streaming) {
      // Phase 2.1: collect everything, answer with one WAV. Same shape as before.
      const bodies = [];
      let fmt = null;
      const out = await runTurn(wav, {
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

gw.connect()
  .then(warmup)
  .then(() => server.listen(PORT, "127.0.0.1",
        () => log(`orchestrator listening on 127.0.0.1:${PORT}, session "${SESSION_KEY}"`)))
  .catch((e) => { log("cannot reach gateway:", e.message); process.exit(1); });

for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => { log("shutting down"); server.close(); process.exit(0); });
}
