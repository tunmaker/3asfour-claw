#!/usr/bin/env python3
"""Wake-word spotting for a streamed microphone, off the Pi.

The Pi carried a 267 MB Vosk model to recognise one word. On a machine with
905 MB of RAM that was the single largest thing running -- 421 MB resident of a
loop whose other job is to move audio around. This does the same work on a host
with eight cores and nine spare gigabytes, and the Pi keeps only an energy gate,
which is arithmetic.

Protocol, deliberately the smallest thing that works:

    POST /listen        chunked request body of raw PCM, 16 kHz s16 mono
                        response is a chunked stream of one JSON object per line

    {"type":"ready"}                        the recogniser is loaded
    {"type":"wake","text":"عباس","at":1.4}  the name was heard, seconds into the stream
    {"type":"speech"} / {"type":"silence"}  energy gate transitions
    {"type":"eof","seconds":12.3}           the client closed the stream

One connection is one listening session. The caller decides what a wake means;
this only reports what it heard.

Runs from the intel-gpu-inference vosk venv, which already has vosk installed --
no new dependency anywhere.
"""
import json
import math
import os
import pathlib
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# The same folding and fuzzy matching the Pi uses, imported rather than
# reimplemented: two copies of "what counts as عبّاس" would eventually disagree,
# and the disagreement would look like the assistant ignoring someone.
sys.path.insert(0, os.environ.get("ABBES_WAKE_DIR", str(pathlib.Path(__file__).resolve().parent)))

from vosk import KaldiRecognizer, Model, SetLogLevel  # noqa: E402

from abbes_match import Matcher, load_decoys  # noqa: E402

SetLogLevel(-1)

RATE = 16000
CHUNK_BYTES = int(RATE * 2 * 0.1)      # 100 ms
HOST = os.environ.get("WAKE_HOST", "0.0.0.0")
PORT = int(os.environ.get("WAKE_PORT", "9093"))
MODEL_PATH = os.environ.get("WAKE_MODEL", str(pathlib.Path.home() / "models/vosk/vosk-model-small-ar-tn-0.1-linto"))
GATE_DBFS = float(os.environ.get("WAKE_GATE_DBFS", "-20"))
GATE_HANGOVER = float(os.environ.get("WAKE_GATE_HANGOVER_SECS", "0.8"))
GRAMMAR = [w for w in os.environ.get("WAKE_WORDS", "عباس|يا عباس|abbes").split("|") if w]
CANDIDATES = [w for w in os.environ.get("WAKE_CANDIDATES", "عباس|عبّاس|abbes|abbas|abes").split("|") if w]
FUZZ = int(os.environ.get("WAKE_FUZZ", "1"))
DECOYS_FILE = os.environ.get("WAKE_DECOYS_FILE", "")

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# Loading the acoustic model takes seconds and megabytes, so it is loaded once
# for the process and shared. KaldiRecognizer is per-connection; Model is not.
log(f"loading {MODEL_PATH}")
_t = time.monotonic()
MODEL = Model(MODEL_PATH)

# Competing words. A grammar holding only the name gives the decoder nothing
# else to choose from, so it forces any speech at all onto the nearest entry and
# reports a wake. Measured without them: "السلام عليكم ورحمة الله" and
# "ما هي المواعيد القادمة" both fired, twice each.
DECOYS = load_decoys(DECOYS_FILE, MODEL_PATH)
GRAMMAR_JSON = json.dumps(GRAMMAR + DECOYS + ["<unk>"], ensure_ascii=False)
log(f"model ready in {time.monotonic() - _t:.1f}s, {len(DECOYS)} decoys")
if not DECOYS:
    log("WARNING: no decoys loaded; the wake word will fire on unrelated speech")


def rms_dbfs(chunk):
    if not chunk:
        return -120.0
    total = 0
    for i in range(0, len(chunk) - 1, 2):
        s = int.from_bytes(chunk[i:i + 2], "little", signed=True)
        total += s * s
    n = len(chunk) // 2
    if n == 0:
        return -120.0
    r = math.sqrt(total / n)
    return 20 * math.log10(r / 32768.0) if r > 0 else -120.0


class Session:
    """One listening stream."""

    def __init__(self):
        self.matcher = Matcher(CANDIDATES, fuzz=FUZZ)
        self.rec = KaldiRecognizer(MODEL, RATE, GRAMMAR_JSON)
        self.samples = 0
        self.open = False
        self.silent_for = 0.0

    def seconds(self):
        return self.samples / (RATE * 2)

    def _final(self):
        """Drain the decoder at the end of an utterance. Returns a hit or None."""
        try:
            text = json.loads(self.rec.FinalResult()).get("text", "")
        except Exception:
            return None
        return self.matcher.find(text) if text else None

    def feed(self, chunk):
        """Yields event dicts."""
        self.samples += len(chunk)
        level = rms_dbfs(chunk)
        secs = len(chunk) / (RATE * 2)

        if level > GATE_DBFS:
            if not self.open:
                self.open = True
                yield {"type": "speech", "at": round(self.seconds(), 2), "dbfs": round(level, 1)}
            self.silent_for = 0.0
        elif self.open:
            self.silent_for += secs
            if self.silent_for >= GATE_HANGOVER:
                self.open = False
                # A short utterance can be decoded only once it ends: partials
                # stay empty and AcceptWaveform never turns over, so the name
                # would sit unread in the decoder forever. A bare "عباس" missed
                # for exactly this reason while "يا عباس، قداش الوقت" was heard.
                #
                # KNOWN DIVERGENCE from the Pi's Listener, which deliberately did
                # NOT reset here: "a pause between يا and عباس is normal speech,
                # and resetting there would throw away the first half of the
                # name." FinalResult drains and resets in one go, so this trades
                # that away to catch short utterances. Which is the better trade
                # can only be settled against a real voice, and until it is,
                # SATELLITE_WAKE stays off on the Pi.
                hit = self._final()
                if hit:
                    yield {"type": "wake", "text": hit, "at": round(self.seconds(), 2)}
                yield {"type": "silence", "at": round(self.seconds(), 2)}

        # The decoder runs roughly at real time on one core, so it is only fed
        # while the gate is open. Feeding it silence is the whole cost.
        if not self.open:
            return

        if self.rec.AcceptWaveform(chunk):
            text = json.loads(self.rec.Result()).get("text", "")
        else:
            text = json.loads(self.rec.PartialResult()).get("partial", "")
        if not text:
            return
        hit = self.matcher.find(text)
        if hit:
            self.rec.Reset()
            yield {"type": "wake", "text": hit, "at": round(self.seconds(), 2)}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/health":
            body = json.dumps({"ok": True, "model": pathlib.Path(MODEL_PATH).name,
                               "gate_dbfs": GATE_DBFS, "words": GRAMMAR,
                               "decoys": len(DECOYS)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/listen":
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        session = Session()
        peer = self.client_address[0]
        log(f"listen: {peer} connected")
        self._emit({"type": "ready"})

        try:
            for chunk in self._chunks():
                for event in session.feed(chunk):
                    if event["type"] == "wake":
                        log(f"listen: wake {event['text']!r} at {event['at']}s")
                    self._emit(event)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log(f"listen: {peer} failed ({e})")
        finally:
            try:
                self._emit({"type": "eof", "seconds": round(session.seconds(), 1)})
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except Exception:
                pass
            log(f"listen: {peer} gone after {session.seconds():.1f}s")

    def _chunks(self):
        """Yield fixed-size PCM chunks from either a chunked or sized body."""
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            buf = b""
            while True:
                line = self.rfile.readline().strip()
                if not line:
                    break
                size = int(line.split(b";")[0], 16)
                if size == 0:
                    self.rfile.readline()
                    break
                buf += self.rfile.read(size)
                self.rfile.readline()
                while len(buf) >= CHUNK_BYTES:
                    yield buf[:CHUNK_BYTES]
                    buf = buf[CHUNK_BYTES:]
            if buf:
                yield buf
            return

        remaining = int(self.headers.get("Content-Length", 0))
        while remaining > 0:
            chunk = self.rfile.read(min(CHUNK_BYTES, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk

    def _emit(self, obj):
        payload = (json.dumps(obj, ensure_ascii=False) + "\n").encode()
        self.wfile.write(b"%x\r\n" % len(payload) + payload + b"\r\n")
        self.wfile.flush()


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    log(f"wake sidecar on {HOST}:{PORT}, gate {GATE_DBFS:g} dBFS, words {GRAMMAR}")
    server.serve_forever()


if __name__ == "__main__":
    main()
