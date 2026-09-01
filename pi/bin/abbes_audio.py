"""One microphone stream, shared by the wake detector and the recorder.

Opening parecord per turn would race the always-on detector for the device, so
the stream is opened once and drained by a background thread. Audio lives in
memory only: the ring buffer is bounded and nothing here writes to disk.

A dead microphone does not announce itself. When the webcam this mic belongs to
wedged, parecord stayed alive and delivered nothing at all for 38 minutes: the
loop sat in read() seeing an unusually quiet room, logged not one line, and
answered no one. So silence is timed. Past DEAD_SECS with the stream unmuted,
the mic is gone rather than quiet, and saying so lets systemd restart the loop
instead of leaving it deaf and looking healthy.
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
        self._muted = False
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
                if not self._muted:
                    self._queue.append(buf)
                    self._ring.append(buf)
                self._cond.notify()

    def read(self, timeout=1.0):
        """Next chunk, or None if nothing arrived (muted, or a quiet timeout)."""
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
        if self._muted:
            return
        quiet_for = self._clock() - self._last_chunk
        if quiet_for >= self._dead_secs:
            self._alive = False
            raise MicGone(f"no audio for {quiet_for:.0f}s; the microphone is gone")

    def preroll(self):
        """The last moment of audio, so a request spoken in one breath isn't clipped."""
        with self._cond:
            return b"".join(self._ring)

    def mute(self):
        with self._cond:
            self._muted = True
            self._queue.clear()
            self._ring.clear()

    def unmute(self):
        with self._cond:
            self._muted = False
            self._queue.clear()
            self._ring.clear()
            # A long mute is not evidence about the device.
            self._last_chunk = self._clock()

    def close(self):
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
