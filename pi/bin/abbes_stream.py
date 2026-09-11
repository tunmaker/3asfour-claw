"""Streamed turn: send the recording to the orchestrator, play speech as it lands.

The old path was four round trips the Pi sequenced itself — Vosk, the gateway over
SSH, Piper, then play a whole file. This is one request. Audio starts at the first
sentence instead of the last, and the Pi does no orchestration at all.

Playback goes through a single long-lived `pw-cat` rather than one `pw-play` per
file, so the sink never suspends between sentences. A suspend costs a wake-up and
is audible as a click at every sentence boundary.

Stdlib only, like the rest of the loop.
"""
import json
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
import io

FRAME_TRANSCRIPT = 1
FRAME_AUDIO = 2
FRAME_END = 3


class Unreachable(Exception):
    pass


def _wav_parts(buf):
    """(pcm_bytes, rate, channels, sampwidth) from a RIFF buffer."""
    with wave.open(io.BytesIO(buf)) as w:
        return (w.readframes(w.getnframes()), w.getframerate(),
                w.getnchannels(), w.getsampwidth())


class PlaybackStream:
    """One pw-cat process fed raw PCM. Opened on the first chunk of a turn.

    pw-cat is told the format up front, so every chunk in a turn must share it —
    Piper always answers 22050 Hz mono 16-bit, and a mismatch raises rather than
    playing noise.
    """

    def __init__(self, sink=None, log=lambda *a: None):
        self.sink = sink
        self.log = log
        self.proc = None
        self.fmt = None
        self._lock = threading.Lock()

    def _open(self, rate, channels, sampwidth):
        cmd = ["pw-cat", "--playback", "-", "--raw",
               "--rate", str(rate), "--channels", str(channels),
               "--format", {1: "u8", 2: "s16", 4: "s32"}[sampwidth]]
        if self.sink:
            cmd += ["--target", self.sink]
        self.log(f"playback: opening stream {rate}Hz {channels}ch")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        self.fmt = (rate, channels, sampwidth)

    def write_wav(self, buf):
        pcm, rate, ch, sw = _wav_parts(buf)
        with self._lock:
            if self.proc is None:
                self._open(rate, ch, sw)
            elif self.fmt != (rate, ch, sw):
                raise Unreachable(f"format changed mid-turn: {self.fmt} -> {(rate, ch, sw)}")
            try:
                self.proc.stdin.write(pcm)
                self.proc.stdin.flush()
            except (BrokenPipeError, ValueError) as e:
                raise Unreachable(f"playback stream died: {e}") from e
        return len(pcm) / (rate * ch * sw)

    def flush(self):
        """Drop anything not yet played. Used for barge-in."""
        with self._lock:
            if self.proc:
                self.proc.kill()
                self.proc = None
                self.fmt = None

    def close(self, should_stop=None, poll=0.1):
        """Close the input and wait for the buffered audio to actually drain.

        Draining is where most of a reply is actually heard: chunks are queued
        far faster than realtime, so by the last frame the speaker still has
        seconds left to play. Polling `should_stop` through the wait is what lets
        an interruption land in the middle of a sentence instead of after it.
        Returns True if it was cut short.
        """
        with self._lock:
            proc, self.proc, self.fmt = self.proc, None, None
        if not proc:
            return False
        try:
            proc.stdin.close()
        except Exception:
            pass
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                proc.wait(timeout=poll)
                return False
            except subprocess.TimeoutExpired:
                pass
            if should_stop and should_stop():
                proc.kill()
                return True
        proc.kill()
        return False


def stream_turn(url, wav_path, player, timeout=180, trigger_words="",
                on_transcript=None, should_stop=None, log=lambda *a: None):
    """POST the recording, play each sentence as it arrives.

    Returns the end frame: {"reply": str, "marks": {...}}, with "interrupted"
    set if the reply was cut short. Hanging up mid-reply is also how the model is
    stopped: the orchestrator aborts the run when this connection closes, so an
    interruption costs no further tokens and leaves no half-turn generating.
    """
    with open(wav_path, "rb") as fh:
        body = fh.read()

    headers = {"Content-Type": "audio/wav"}
    if trigger_words:
        # STT happens server-side now, so the wake word is stripped there too.
        # HTTP headers are latin-1; the wake words are Arabic, so percent-encode.
        headers["X-Abbes-Trigger-Words"] = urllib.parse.quote(trigger_words)
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise Unreachable(f"orchestrator: {e}") from e

    result = {"reply": "", "marks": {}}
    chunks = 0
    interrupted = False
    try:
        while True:
            if should_stop and should_stop():
                interrupted = True
                break
            head = _read_exactly(resp, 5)
            if head is None:
                break
            kind = head[0]
            (length,) = struct.unpack(">I", head[1:5])
            body = _read_exactly(resp, length)
            if body is None:
                raise Unreachable("orchestrator: truncated frame")

            if kind == FRAME_TRANSCRIPT:
                text = json.loads(body).get("text", "")
                on_transcript and on_transcript(text)
            elif kind == FRAME_AUDIO:
                secs = player.write_wav(body)
                chunks += 1
                log(f"  chunk {chunks}: {secs:.1f}s queued")
            elif kind == FRAME_END:
                result = json.loads(body)
                break
    finally:
        resp.close()

    if interrupted:
        player.flush()
    elif chunks and player.close(should_stop=should_stop):
        interrupted = True
    result["interrupted"] = interrupted
    return result


def _read_exactly(fh, n):
    buf = b""
    while len(buf) < n:
        c = fh.read(n - len(buf))
        if not c:
            return None
        buf += c
    return buf
