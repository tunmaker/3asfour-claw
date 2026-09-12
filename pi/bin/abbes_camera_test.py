#!/usr/bin/env python3
"""Checks the wedge back-off and self-repair. Run: python3 abbes_camera_test.py"""
import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from abbes_camera import CameraPoller, frame_url

FAILS = []


def check(name, cond):
    print(f"{'ok  ' if cond else 'FAIL'} {name}")
    if not cond:
        FAILS.append(name)


class FakeCamera:
    device = "/dev/video0"

    def __init__(self, frames):
        self.frames = list(frames)
        self.grabs = 0

    def grab(self):
        self.grabs += 1
        return self.frames.pop(0) if self.frames else None


def poller(frames, **kw):
    p = CameraPoller("http://x/vision/frame", FakeCamera(frames), **kw)
    p._post = lambda frame: None
    p._stop = threading.Event()
    return p


def pump(p, n, waits=None):
    """Run the poll body n times, recording the interval it would have waited."""
    p._stop.wait = (lambda t: waits.append(t)) if waits is not None else (lambda _t: None)
    t = threading.Thread(target=p._run, daemon=True)
    counter = {"n": 0}
    real = p.camera.grab

    def counted():
        counter["n"] += 1
        if counter["n"] > n:
            p._stop.set()
        return real()

    p.camera.grab = counted
    t.start()
    t.join(timeout=5)
    return not t.is_alive()


# A healthy camera never declares a wedge.
p = poller([b"x" * 2000] * 20)
pump(p, 15)
check("healthy polling is never wedged", not p.wedged)

# Ten failures in a row is a wedge.
p = poller([], wedge_after=10)
pump(p, 12)
check("ten failures is a wedge", p.wedged)

# A wedge backs the interval off instead of hammering.
p = poller([], wedge_after=3, interval=3.0, wedge_interval=300.0)
waits = []
pump(p, 6, waits)
check("polls fast before the wedge", waits[0] > 2.0 and waits[1] > 2.0)
check("backs off hard after the wedge", waits[-1] > 200)

# The reset runs, but only when the loop is idle.
p = poller([], wedge_after=2, repair=lambda: True, idle=lambda: False)
pump(p, 6)
check("no reset while a turn is in flight", p.repairs == 0)

calls = []
p = poller([], wedge_after=2, repair=lambda: calls.append(1) or True, idle=lambda: True)
pump(p, 5)
check("resets once idle", p.repairs > 0 and len(calls) > 0)

# A reset that throws must not kill the thread.
p = poller([], wedge_after=2, repair=lambda: (_ for _ in ()).throw(OSError("nope")),
           idle=lambda: True)
done = pump(p, 5)
check("a failing reset does not kill the poller", done)

# Recovery clears the wedge and returns to the fast interval.
p = poller([None, None, None, b"x" * 2000, b"x" * 2000], wedge_after=2)
p.camera.frames = [None, None, None, b"x" * 2000, b"x" * 2000]
p.camera.grab = lambda: p.camera.frames.pop(0) if p.camera.frames else None
pump(p, 5)
check("a good frame clears the wedge", not p.wedged)

check("frame url derives from the turn url",
      frame_url("http://h:18790/turn") == "http://h:18790/vision/frame")

# A wedge must outlive the process. Holding the count in memory alone is what
# let a loop restarting every 38s hammer a dead camera forever: it never once
# reached wedge_after, so the back-off could not engage.
import tempfile
tmp = pathlib.Path(tempfile.mkdtemp()) / "nested" / "failures"

p1 = poller([], wedge_after=3, state=str(tmp))
pump(p1, 3)
check("failures are written to the state file, parents created",
      tmp.read_text().strip() == str(p1.consecutive_failures) and p1.consecutive_failures >= 3)
check("and that is a wedge", p1.wedged)

p2 = poller([], wedge_after=3, state=str(tmp))
check("a fresh poller starts already wedged, as a restart would",
      p2.wedged and p2.consecutive_failures == p1.consecutive_failures)

p3 = poller([b"a frame"], wedge_after=3, state=str(tmp))
pump(p3, 0)
check("a good frame clears the file too", tmp.read_text().strip() == "0" and not p3.wedged)

p4 = poller([], wedge_after=3, state="/proc/nope/cannot/write")
pump(p4, 3)
check("an unwritable state path is not fatal", p4.wedged)

check("a corrupt state file reads as zero",
      (tmp.write_text("banana"), poller([], wedge_after=3, state=str(tmp)).consecutive_failures)[1] == 0)

check("no state path still works", poller([], wedge_after=2).consecutive_failures == 0)

print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'all checks passed'}")
sys.exit(1 if FAILS else 0)
