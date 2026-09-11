#!/usr/bin/env python3
"""Checks the mic watchdog and barge-in. Run: python3 abbes_audio_test.py"""
import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from abbes_audio import CHUNK_BYTES, BargeIn, MicGone, MicStream

FAILS = []


def check(name, cond):
    print(f"{'ok  ' if cond else 'FAIL'} {name}")
    if not cond:
        FAILS.append(name)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeProc:
    """Stands in for parecord: yields chunks on demand, never exits."""

    def __init__(self):
        self.gate = threading.Semaphore(0)
        self.stdout = self

    def read(self, n):
        self.gate.acquire()
        return b"\x00" * n

    def deliver(self):
        self.gate.release()


def stream(clock, dead_secs=30.0):
    s = MicStream.__new__(MicStream)
    proc = FakeProc()
    s._proc = proc
    import collections
    s._ring = collections.deque(maxlen=10)
    s._queue = collections.deque(maxlen=50)
    s._cond = threading.Condition()
    s._alive = True
    s._dead_secs = dead_secs
    s._clock = clock
    s._last_chunk = clock()
    s._pump = threading.Thread(target=s._drain, daemon=True)
    s._pump.start()
    return s, proc


clock = FakeClock()
s, proc = stream(clock)

check("a quiet room is not a dead mic", s.read(timeout=0.05) is None)

clock.t += 29
check("under the deadline stays quiet, not fatal", s.read(timeout=0.05) is None)

clock.t += 2
try:
    s.read(timeout=0.05)
    check("past the deadline raises MicGone", False)
except MicGone as e:
    check("past the deadline raises MicGone", True)
    check("the message says how long", "31s" in str(e))

# Audio arriving resets the clock.
clock = FakeClock()
s, proc = stream(clock)
clock.t += 20
proc.deliver()
got = s.read(timeout=2.0)
check("a delivered chunk is returned", got is not None and len(got) == CHUNK_BYTES)
clock.t += 20
check("a chunk resets the deadline", s.read(timeout=0.05) is None)

# The microphone is never muted now, so silence is always evidence about the
# device. Nothing is exempt from the deadline.
clock = FakeClock()
s_, proc = stream(clock)
clock.t += 31
try:
    s_.read(timeout=0.05)
    check("silence past the deadline raises", False)
except MicGone as e:
    check("silence past the deadline raises", "microphone is gone" in str(e))

# drain() throws away the backlog without disturbing the watchdog.
clock = FakeClock()
s_, proc = stream(clock)
proc.deliver()
check("a chunk is queued before draining", s_.read(timeout=2.0) is not None)
proc.deliver()
for _ in range(200):
    with s_._cond:
        if s_._queue:
            break
    time.sleep(0.01)
s_.drain()
check("drain empties the backlog", s_.read(timeout=0.05) is None)

# An exit is still an exit, and takes priority.
clock = FakeClock()
s, proc = stream(clock)
with s._cond:
    s._alive = False
    s._cond.notify_all()
try:
    s.read(timeout=0.05)
    check("a dead process still raises", False)
except MicGone as e:
    check("a dead process still raises", "exited" in str(e))

# Barge-in: quiet is ignored, sustained speech fires, and what was said is kept.
LOUD = (b"\x00\x40" * (CHUNK_BYTES // 2))
QUIET = b"\x00\x00" * (CHUNK_BYTES // 2)


class FakeStream:
    """Hands out a scripted sequence of chunks, then blocks on silence."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.drained = False

    def drain(self):
        self.drained = True

    def read(self, timeout=1.0):
        return self.chunks.pop(0) if self.chunks else None



fs = FakeStream([QUIET] * 5)
with BargeIn(fs, threshold_dbfs=-30, min_speech_secs=0.35) as w:
    time.sleep(0.3)
check("a quiet room never fires", not w.fired)
check("entering drains the backlog first", fs.drained)

fs = FakeStream([LOUD] * 8)
with BargeIn(fs, threshold_dbfs=-30, min_speech_secs=0.35) as w:
    time.sleep(0.3)
check("sustained speech fires", w.fired)
check("and the interruption is kept", len(w.speech()) >= CHUNK_BYTES * 3)

# One loud chunk is a door or a cough, not someone talking over you.
fs = FakeStream([QUIET, LOUD, QUIET, QUIET, QUIET])
with BargeIn(fs, threshold_dbfs=-30, min_speech_secs=0.35) as w:
    time.sleep(0.3)
check("a single transient does not fire", not w.fired)

# A microphone that dies mid-playback must not take the watcher down with it.
class DeadStream(FakeStream):
    def read(self, timeout=1.0):
        raise MicGone("gone")

with BargeIn(DeadStream([]), threshold_dbfs=-30) as w:
    time.sleep(0.1)
check("a dead mic ends the watcher quietly", not w.fired)

print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'all checks passed'}")
