"""python3 pi/bin/abbes_wake_test.py   (run from the repo root)

Does the wake gate follow the room? A fixed threshold is wrong twice a day: the
same microphone at the same gain measured a -24.8 dBFS floor at 3am and -36.3 at
4pm, and a gate set for the first left the assistant completely deaf during the
second -- 0 of 39 windows crossed it.

Uses the real Listener with a stub detector, so what is under test is the gate
and not Vosk.
"""
import array, math, pathlib, struct, sys
sys.path.insert(0, str(pathlib.Path("pi/bin").resolve()))
import abbes_wake
from abbes_audio import CHUNK_MS

RATE = 16000
CHUNK = int(RATE * CHUNK_MS / 1000)

def noise(dbfs, n=CHUNK):
    amp = 32767 * 10 ** (dbfs / 20)
    # deterministic pseudo-noise at a known RMS
    return array.array("h", [int(amp * (1 if (i * 7919) % 2 else -1)) for i in range(n)]).tobytes()

class StubDetector:
    def __init__(self): self.fed = 0
    def feed(self, c): self.fed += 1; return None
    def reset(self): pass

fails = 0
def check(label, got, want, tol=2.0):
    global fails
    ok = abs(got - want) <= tol
    if not ok: fails += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got:.1f} (want ~{want:.1f})")

for floor, label in ((-36.3, "a quiet afternoon"), (-24.8, "a noisy 3am")):
    L = abbes_wake.Listener(StubDetector(), threshold_dbfs=-20.0, window_secs=30)
    for _ in range(400):
        L.feed(noise(floor))
    check(f"{label}, floor {floor}", L.threshold, floor + 8)

# Speech must not drag the floor up with it.
L = abbes_wake.Listener(StubDetector(), threshold_dbfs=-20.0, window_secs=30)
for i in range(400):
    L.feed(noise(-36.0 if i % 4 else -15.0))   # a quarter of the time, someone talks
check("floor with 25% speech present", L.threshold, -36.0 + 8, tol=3.0)

# Clamps.
L = abbes_wake.Listener(StubDetector(), threshold_dbfs=-20.0, max_threshold=-18.0)
for _ in range(400): L.feed(noise(-5.0))
check("a very loud room is clamped", L.threshold, -18.0, tol=0.1)
L = abbes_wake.Listener(StubDetector(), threshold_dbfs=-20.0, min_threshold=-48.0)
for _ in range(400): L.feed(noise(-90.0))
check("a silent room is clamped", L.threshold, -48.0, tol=0.1)

# Adaptation off leaves the configured value alone.
L = abbes_wake.Listener(StubDetector(), threshold_dbfs=-20.0, adapt=False)
for _ in range(400): L.feed(noise(-36.0))
check("adapt=False keeps the configured threshold", L.threshold, -20.0, tol=0.01)

# The gate must actually open on speech once adapted.
L = abbes_wake.Listener(StubDetector(), threshold_dbfs=-20.0)
for _ in range(400): L.feed(noise(-36.0))
before = L.detector.fed
for _ in range(10): L.feed(noise(-18.0))
print(f"  {'ok  ' if L.detector.fed > before else 'FAIL'} speech reaches the decoder after adapting "
      f"({L.detector.fed - before} chunks)")
fails += 0 if L.detector.fed > before else 1

print(f"\n  {'all good' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
