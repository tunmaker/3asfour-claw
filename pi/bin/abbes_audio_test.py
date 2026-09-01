#!/usr/bin/env python3
"""Checks the mic watchdog. Run: python3 abbes_audio_test.py"""
import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from abbes_audio import CHUNK_BYTES, MicGone, MicStream

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
    s._muted = False
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

# A long mute must not look like a dead device.
clock = FakeClock()
s, proc = stream(clock)
s.mute()
clock.t += 600
check("muted silence is never fatal", s.read(timeout=0.05) is None)
s.unmute()
clock.t += 10
check("unmute restarts the clock", s.read(timeout=0.05) is None)
clock.t += 25
try:
    s.read(timeout=0.05)
    check("the deadline still applies after unmute", False)
except MicGone:
    check("the deadline still applies after unmute", True)

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

print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'all checks passed'}")
sys.exit(1 if FAILS else 0)
