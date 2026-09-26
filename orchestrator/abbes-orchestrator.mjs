// The voice path, in one place: the Pi sends a recording, gets speech back.
//
//   POST /turn/stream  WAV in -> length-prefixed frames out:
//                      1 = transcript JSON, 2 = one WAV per sentence, 3 = end JSON
//   GET  /health
//
// whisper -> the gateway's voice session -> Piper, sentence by sentence, so the
// first sentence plays while the model is still writing the rest.

import http from "node:http";
import { GatewayClient } from "./gateway-client.mjs";
import { Chunker } from "./sentences.mjs";
import { cleanTranscript, stripName } from "./transcript.mjs";

const PORT        = +(process.env.ABBES_ORCH_PORT || 18790);
const GW_URL      = process.env.GW_URL || "ws://127.0.0.1:18789";
const ENV_FILE    = process.env.OPENCLAW_ENV || `${process.env.HOME}/.openclaw/openclaw.env`;
const STT_URL     = process.env.STT_URL || required("STT_URL");
const TTS_URL     = process.env.TTS_URL || required("TTS_URL");
const SESSION_KEY = process.env.ABBES_SESSION_KEY || "agent:main:voice";
const VOICE       = process.env.PIPER_VOICE || "en_US-lessac-medium";
const STT_TIMEOUT = +(process.env.STT_TIMEOUT_MS || 30000);
const TTS_TIMEOUT = +(process.env.TTS_TIMEOUT_MS || 15000);
const IDLE_RESET  = +(process.env.ABBES_VOICE_IDLE_RESET_MS || 30 * 60 * 1000);

const FRAME_TRANSCRIPT = 1, FRAME_AUDIO = 2, FRAME_END = 3;

function required(name) {
  console.error(`[orchestrator] ${name} is not set`);
  process.exit(2);
}

const log = (...a) => console.log(`[${new Date().toISOString().slice(11, 23)}]`, ...a);

async function transcribe(wav) {
  const form = new FormData();
  form.append("file", new Blob([wav], { type: "audio/wav" }), "turn.wav");
  form.append("response_format", "json");
  form.append("prompt", "Abbes,");
  const res = await fetch(STT_URL, { method: "POST", body: form, signal: AbortSignal.timeout(STT_TIMEOUT) });
  if (!res.ok) throw new Error(`stt ${res.status}`);
  const d = await res.json();
  if (d.error) throw new Error(`stt: ${d.error}`);
  return (d.text || "").trim();
}

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

const gw = new GatewayClient({ url: GW_URL, envFile: ENV_FILE, log,
  scopes: ["operator.read", "operator.write", "operator.admin"] });

let lastTurnAt = 0;

// Voice history is worth minutes, not days, and a short session keeps the
// prompt small enough to stay fast.
async function maybeResetSession() {
  if (!lastTurnAt || Date.now() - lastTurnAt < IDLE_RESET) return;
  log("voice session reset (idle)");
  try { await gw.call("sessions.reset", { key: SESSION_KEY }); }
  catch (e) { log("reset failed:", e.message); }
}

async function runTurn(wav, { onTranscript, onAudio }) {
  const t0 = Date.now();
  const marks = {};

  const heard = cleanTranscript(await transcribe(wav));
  const request = stripName(heard);
  marks.sttMs = Date.now() - t0;
  log(`heard: ${JSON.stringify(heard)}`);
  onTranscript(request);
  if (!request) return { transcript: "", reply: "", marks };

  let queue = Promise.resolve();
  let index = 0;
  const speak = (sentence) => {
    if (sentence.trimStart().startsWith("⚠")) return;
    queue = queue.then(async () => {
      const audio = await synthesize(sentence);
      if (marks.firstAudioMs === undefined) marks.firstAudioMs = Date.now() - t0;
      await onAudio(audio, index++);
    }).catch((e) => log("tts failed:", e.message));
  };

  await maybeResetSession();
  const chunker = new Chunker();
  const turn = await gw.sendTurn(SESSION_KEY, `[voice] ${request}`, {
    onDelta: (delta, full, replaced) => {
      if (replaced) { chunker.replace(full); return; }
      for (const s of chunker.push(delta)) speak(s);
    },
    onToolStart: (name) => log(`  tool: ${name}`),
  });
  for (const s of chunker.end()) speak(s);
  lastTurnAt = Date.now();
  await queue;

  marks.firstDeltaMs = turn.firstDeltaMs;
  marks.totalMs = Date.now() - t0;
  return { transcript: request, reply: turn.text || "", marks };
}

function frame(kind, body) {
  const h = Buffer.alloc(5);
  h.writeUInt8(kind, 0);
  h.writeUInt32BE(body.length, 1);
  return Buffer.concat([h, body]);
}

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

let busy = false;

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");

  if (req.method === "GET" && url.pathname === "/health") {
    res.writeHead(gw.ready ? 200 : 503, { "content-type": "application/json" });
    res.end(JSON.stringify({ ok: gw.ready, busy, session: SESSION_KEY }));
    return;
  }

  if (req.method !== "POST" || url.pathname !== "/turn/stream") {
    res.writeHead(404).end("not found");
    return;
  }

  let wav;
  try { wav = await readBody(req); }
  catch (e) { res.writeHead(413).end(e.message); return; }

  res.writeHead(200, { "content-type": "application/octet-stream", "cache-control": "no-store" });

  // The Pi hangs up when someone talks over the reply; stop generating then.
  req.on("close", () => { if (!res.writableEnded) { log("client hung up; aborting"); gw.abort(SESSION_KEY); } });

  busy = true;
  try {
    const out = await runTurn(wav, {
      onTranscript: (text) => res.write(frame(FRAME_TRANSCRIPT, Buffer.from(JSON.stringify({ text })))),
      onAudio: (buf, i) => new Promise((resolve) => {
        log(`  sentence ${i} (${buf.length}b)`);
        res.write(frame(FRAME_AUDIO, buf), () => resolve());
      }),
    });
    res.end(frame(FRAME_END, Buffer.from(JSON.stringify({ reply: out.reply, marks: out.marks }))));
    log(`turn: ${JSON.stringify(out.transcript)} -> ${JSON.stringify(out.reply.slice(0, 80))} ` +
        `stt ${out.marks.sttMs}ms first-audio ${out.marks.firstAudioMs}ms total ${out.marks.totalMs}ms`);
  } catch (e) {
    log("turn failed:", e.message);
    res.end(frame(FRAME_END, Buffer.from(JSON.stringify({ reply: "", error: e.message }))));
  } finally {
    busy = false;
  }
});

gw.connect()
  .then(() => server.listen(PORT, "127.0.0.1", () => log(`listening on 127.0.0.1:${PORT}, session ${SESSION_KEY}`)))
  .catch((e) => { log("cannot reach gateway:", e.message); process.exit(1); });

for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => { server.close(); process.exit(0); });
}
