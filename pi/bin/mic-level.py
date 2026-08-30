#!/usr/bin/env python3
"""Live microphone level meter, for setting the VAD and wake-gate thresholds.

Shows what the microphone actually hears, against the two thresholds that decide
whether a turn happens. Speak normally from where you usually stand.
"""

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from abbes_audio import CHUNK_MS, MicStream, rms_dbfs
from abbes_config import cfg

GATE = cfg("WAKE_GATE_DBFS", "-30", float)
VAD = cfg("VAD_THRESHOLD_DBFS", "-30", float)
MIN_SPEECH = cfg("VAD_MIN_SPEECH_SECS", "0.5", float)


def bar(db, lo=-60.0, hi=0.0, width=40):
    n = max(0, min(width, int((db - lo) / (hi - lo) * width)))
    return "#" * n + "-" * (width - n)


def main():
    stream = MicStream(cfg("MIC_SOURCE"), 1.0)
    print(f"gate {GATE:g} dBFS (wake word)   vad {VAD:g} dBFS (recorder, needs "
          f"{MIN_SPEECH:g}s sustained)\nspeak normally. ctrl-c for a summary.\n", flush=True)
    levels = []
    voiced = 0.0
    armed_ever = False
    try:
        while True:
            chunk = stream.read()
            if chunk is None:
                continue
            db = rms_dbfs(chunk)
            levels.append(db)
            if db > VAD:
                voiced += CHUNK_MS / 1000.0
            else:
                voiced = 0.0
            armed = voiced >= MIN_SPEECH
            armed_ever |= armed
            flags = f"{'GATE ' if db > GATE else '     '}{'ARMED' if armed else '     '}"
            print(f"\r{db:7.1f} dBFS |{bar(db)}| {flags}", end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        stream.close()

    if not levels:
        print("\nno audio captured at all — is the microphone connected?")
        return
    levels.sort()
    n = len(levels)
    p = lambda q: levels[min(n - 1, int(n * q))]
    print(f"\n\n{n * CHUNK_MS / 1000:.0f}s sampled")
    print(f"  quietest (p10) {p(0.10):6.1f} dBFS   <- room floor")
    print(f"  median         {p(0.50):6.1f}")
    print(f"  loud (p90)     {p(0.90):6.1f}")
    print(f"  peak           {levels[-1]:6.1f}   <- your voice")
    print(f"\n  recorder armed at some point: {'yes' if armed_ever else 'NO — this is why turns fail'}")
    floor, loud = p(0.10), p(0.90)
    if loud - floor < 6:
        print("\n  Speech is barely above the room floor. Move closer to the mic, or raise")
        print("  its gain, before changing any threshold.")
    else:
        suggested = round((floor + loud) / 2)
        print(f"\n  suggested VAD_THRESHOLD_DBFS / WAKE_GATE_DBFS: {suggested}")
        print(f"  (midway between floor {floor:.0f} and speech {loud:.0f})")


if __name__ == "__main__":
    main()
