"""One microphone stream, shared by the wake detector, the recorder and barge-in.

Opening parecord per turn would race the always-on detector for the device, so
the stream is opened once and drained by a background thread. Audio lives in
memory only: the ring buffer is bounded and nothing here writes to disk.

The microphone is never muted. It used to be, across every moment Abbes spoke,
because the speaker and the microphone were separate devices in one room and the
microphone heard the reply. They are now one device -- a Jabra SPEAK 510 -- which
cancels its own output in hardware: a tone loud enough to fill the room measures
-48.9 dBFS at this microphone, below the room's own noise floor of -45.7. The
microphone cannot hear the speaker, so there is nothing to mute, and holding it
open is what makes interrupting Abbes mid-sentence possible.

A dead microphone does not announce itself: parecord stays alive and delivers
nothing, and the loop sits in read() seeing an unusually quiet room. So silence
is timed. Past DEAD_SECS the mic is gone rather than quiet, and saying so lets
systemd restart the loop instead of leaving it deaf and looking healthy.
"""

import array
import collections
import math
import subprocess
import threading
import time
import wave

RATE = 16000
CHUNK_MS = 100
CHUNK_BYTES = int(RATE * 2 * CHUNK_MS / 1000)

# Generous: a healthy stream delivers ten chunks a second, so anything near this
# is broken, not idle.
DEAD_SECS = 30.0


class MicGone(Exception):
    pass


def rms_dbfs(buf):
    a = array.array("h")
    a.frombytes(buf[: len(buf) // 2 * 2])
    if not a:
        return -120.0
    rms = math.sqrt(sum(float(x) * x for x in a) / len(a))
    return 20 * math.log10(rms / 32768.0) if rms > 0 else -120.0


def write_tone(path, freqs=(880, 1320), secs=0.08, rate=RATE, volume=0.25):
    """A two-note chirp, so the trigger is audible without waiting on Piper."""
    frames = array.array("h")
    for f in freqs:
        n = int(rate * secs)
        for i in range(n):
            fade = min(1.0, min(i, n - i) / (rate * 0.01))
            frames.append(int(volume * fade * 32767 * math.sin(2 * math.pi * f * i / rate)))
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames.tobytes())
    return path


class MicStream:
    def __init__(self, source=None, preroll_secs=1.0, backlog_secs=5.0,
                 dead_secs=DEAD_SECS, clock=time.monotonic):
        cmd = ["parecord", "--raw", f"--rate={RATE}", "--channels=1", "--format=s16le"]
        if source:
            cmd += ["-d", source]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self._ring = collections.deque(maxlen=self._chunks(preroll_secs))
        self._queue = collections.deque(maxlen=self._chunks(backlog_secs))
        self._cond = threading.Condition()
        self._alive = True
        self._dead_secs = dead_secs
        self._clock = clock
        self._last_chunk = clock()
        self._pump = threading.Thread(target=self._drain, daemon=True)
        self._pump.start()

    @staticmethod
    def _chunks(secs):
        return max(1, int(secs * 1000 / CHUNK_MS))

    def _drain(self):
        while True:
            buf = self._proc.stdout.read(CHUNK_BYTES)
            with self._cond:
                if not buf:
                    self._alive = False
                    self._cond.notify_all()
                    return
                self._last_chunk = self._clock()
                self._queue.append(buf)
                self._ring.append(buf)
                self._cond.notify()

    def read(self, timeout=1.0):
        """Next chunk, or None if nothing arrived within the timeout."""
        with self._cond:
            if not self._queue and self._alive:
                self._cond.wait(timeout)
            if not self._queue:
                if not self._alive:
                    raise MicGone("parecord exited")
                self._check_alive()
                return None
            return self._queue.popleft()

    def _check_alive(self):
        """Silence is only ever silence for so long. Caller holds the lock."""
        quiet_for = self._clock() - self._last_chunk
        if quiet_for >= self._dead_secs:
            self._alive = False
            raise MicGone(f"no audio for {quiet_for:.0f}s; the microphone is gone")

    def preroll(self):
        """The last moment of audio, so a request spoken in one breath isn't clipped."""
        with self._cond:
            return b"".join(self._ring)

    def drain(self):
        """Drop whatever is buffered, so the next read starts from now."""
        with self._cond:
            self._queue.clear()
            self._ring.clear()

    def close(self):
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()


class BargeIn:
    """Watches for someone talking over Abbes, and keeps what they said.

    Only possible because this microphone hears nothing of the speaker beside it
    (see the module docstring), so anything clearing the threshold while Abbes is
    talking is a person, not the reply. Used as a context manager around
    playback; `fired` says whether to stop.

    The audio from the moment speech began is kept. Interrupting is then one
    movement -- Abbes stops and answers what you said -- instead of Abbes
    stopping and asking you to say it again, which is what makes an interruption
    feel like being heard rather than like hitting a button.
    """

    def __init__(self, stream, threshold_dbfs=-30.0, min_speech_secs=0.35,
                 log=lambda *a: None):
        self._stream = stream
        self._threshold = threshold_dbfs
        self._min_chunks = max(1, int(min_speech_secs * 1000 / CHUNK_MS))
        self._log = log
        self._fired = threading.Event()
        self._stop = threading.Event()
        self._speech = bytearray()
        self._thread = None

    def __enter__(self):
        self._stream.drain()
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        return False

    @property
    def fired(self):
        return self._fired.is_set()

    def speech(self):
        return bytes(self._speech)

    def _watch(self):
        run = bytearray()
        voiced = 0
        while not self._stop.is_set():
            try:
                buf = self._stream.read(timeout=0.2)
            except MicGone:
                return
            if buf is None:
                continue
            if self._fired.is_set():
                self._speech += buf
                continue
            level = rms_dbfs(buf)
            if level > self._threshold:
                run += buf
                voiced += 1
                if voiced >= self._min_chunks:
                    self._speech = run
                    self._fired.set()
                    self._log(f"barge-in: you started speaking ({level:.0f} dBFS), stopping")
            else:
                run = bytearray()
                voiced = 0
