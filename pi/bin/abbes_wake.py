#!/usr/bin/env python3
"""Vosk keyword spotting for the name Abbes.

Audio is decoded on this Pi and discarded. Nothing is transmitted, written or
logged until the name is actually recognised: the only text this module emits
is the matched trigger phrase itself.

Two things make this affordable on a Pi 3B. The recogniser is restricted to a
small grammar rather than transcribing freely, and an energy gate keeps the
decoder asleep until someone is actually speaking -- the acoustic model runs at
roughly real time on this hardware, so it cannot be left running on silence.

Standalone:  abbes_wake.py --listen [--tally FILE]
"""

import collections
import json
import pathlib
import re
import sys
import time
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from abbes_audio import CHUNK_MS, MicStream, rms_dbfs

from abbes_match import (  # noqa: F401  (re-exported for callers of this module)
    DEFAULT_CANDIDATES,
    DEFAULT_GRAMMAR,
    Matcher,
    load_decoys,
    normalize,
    within,
)


class Detector:
    """Grammar-restricted Vosk recogniser that reports only the trigger phrase."""

    def __init__(self, model_path, grammar=None, candidates=None, fuzz=1, rate=16000):
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)
        self.rate = rate
        self.model = Model(model_path)
        words = list(grammar if grammar is not None else DEFAULT_GRAMMAR)
        self.grammar = json.dumps(words + ["<unk>"], ensure_ascii=False) if words else None
        self.matcher = Matcher(candidates if candidates is not None else DEFAULT_CANDIDATES, fuzz)
        self.reset()

    def reset(self):
        from vosk import KaldiRecognizer
        self._rec = (KaldiRecognizer(self.model, self.rate, self.grammar)
                     if self.grammar else KaldiRecognizer(self.model, self.rate))

    def feed(self, chunk):
        """Matched phrase as soon as it appears in the hypothesis, else None.

        Partials are checked so the trigger fires mid-sentence rather than
        waiting for the speaker to fall silent.
        """
        if self._rec.AcceptWaveform(chunk):
            text = json.loads(self._rec.Result()).get("text", "")
        else:
            text = json.loads(self._rec.PartialResult()).get("partial", "")
        hit = self.matcher.find(text)
        if hit:
            self.reset()
        return hit


class Listener:
    """Energy-gated wake detection, with the gate tracking the room.

    The decoder costs about one second of CPU per second of audio on this Pi,
    so it is only fed while the room is above the noise floor. Quiet rooms cost
    nothing; the gate reopens on the first loud chunk and holds through the
    short pauses inside a sentence.

    Closing the gate does not reset the recogniser. A pause between "يا" and
    "عباس" is normal speech, and resetting there would throw away the first
    half of the name. State is only discarded once the room has been quiet long
    enough that whatever was being said is over.

    The threshold adapts, because a fixed one is wrong twice a day. Measured in
    this room, same microphone, same gain:

        3am ... floor -24.8 dBFS median, -21.7 max
        4pm ... floor -36.3 dBFS median, -26.9 max

    A threshold set against the first is 12 dB above the second and the
    assistant goes completely deaf: 0 of 39 windows crossed it, so the decoder
    was never fed and the name could not be heard however loudly it was said.
    Set against the second it never closes at night. So it is kept a fixed
    margin above a running estimate of the floor rather than at a fixed number.

    Erring low is the cheap direction. Too low costs CPU decoding room noise;
    too high costs everything. False wakes are the decoys' job, not the gate's.
    """

    def __init__(self, detector, threshold_dbfs=-30.0, hangover_secs=0.8, idle_reset_secs=2.0,
                 adapt=True, margin_db=8.0, window_secs=30.0, floor_percentile=0.25,
                 min_threshold=-48.0, max_threshold=-18.0):
        self.detector = detector
        self.threshold = threshold_dbfs
        self.configured_threshold = threshold_dbfs
        self.hangover_chunks = max(1, int(hangover_secs * 1000 / CHUNK_MS))
        self.idle_reset_chunks = max(self.hangover_chunks + 1, int(idle_reset_secs * 1000 / CHUNK_MS))
        self._quiet = 0
        self._stale = False
        self.decoded_chunks = 0
        self.total_chunks = 0

        self.adapt = adapt
        self.margin_db = margin_db
        self.floor_percentile = floor_percentile
        self.min_threshold = min_threshold
        self.max_threshold = max_threshold
        self._levels = collections.deque(maxlen=max(20, int(window_secs * 1000 / CHUNK_MS)))
        # Recomputed on a cadence rather than per chunk: sorting 300 floats every
        # 100 ms would be a real cost on this hardware for no extra accuracy.
        self._recalc_every = max(10, int(5000 / CHUNK_MS))
        self._since_recalc = 0
        self.noise_floor = None

    def _recalc(self):
        """Threshold = a margin above the quiet quarter of what we have heard.

        The percentile is what makes speech not raise the floor: someone talking
        occupies the loud end of the window, so the quiet end still describes the
        room they are talking in.
        """
        if len(self._levels) < self._levels.maxlen // 4:
            return
        ordered = sorted(self._levels)
        floor = ordered[int(len(ordered) * self.floor_percentile)]
        if floor <= -119:                      # a dead or muted microphone
            return
        self.noise_floor = floor
        self.threshold = min(self.max_threshold,
                             max(self.min_threshold, floor + self.margin_db))

    def feed(self, chunk):
        self.total_chunks += 1
        level = rms_dbfs(chunk)
        if self.adapt:
            self._levels.append(level)
            self._since_recalc += 1
            if self._since_recalc >= self._recalc_every:
                self._since_recalc = 0
                self._recalc()
        loud = level > self.threshold
        if loud:
            self._quiet = 0
            self._stale = False
        else:
            self._quiet += 1
            if self._quiet > self.idle_reset_chunks:
                if not self._stale:
                    self.detector.reset()
                    self._stale = True
                return None
            if self._quiet > self.hangover_chunks:
                return None
        self.decoded_chunks += 1
        return self.detector.feed(chunk)

    def reset(self):
        self._quiet = 0
        self._stale = False
        self.detector.reset()

    @property
    def gate_open(self):
        return self._quiet <= self.hangover_chunks

    @property
    def duty(self):
        return self.decoded_chunks / self.total_chunks if self.total_chunks else 0.0


def build(cfg, listing):
    model = cfg("WAKE_MODEL")
    if not model:
        raise RuntimeError("WAKE_MODEL not configured")
    grammar = listing("WAKE_WORDS") or list(DEFAULT_GRAMMAR)
    grammar += [w for w in load_decoys(cfg("WAKE_DECOYS_FILE"), model) if w not in grammar]
    detector = Detector(model, grammar,
                        listing("WAKE_CANDIDATES") or DEFAULT_CANDIDATES,
                        cfg("WAKE_FUZZ", "1", int))
    return Listener(detector,
                    cfg("WAKE_GATE_DBFS", "-30", float),
                    cfg("WAKE_GATE_HANGOVER_SECS", "0.8", float),
                    cfg("WAKE_GATE_IDLE_RESET_SECS", "2.0", float),
                    adapt=str(cfg("WAKE_GATE_ADAPT", "1")).strip() not in ("0", "false", "no"),
                    margin_db=cfg("WAKE_GATE_MARGIN_DB", "8", float),
                    window_secs=cfg("WAKE_GATE_WINDOW_SECS", "30", float),
                    min_threshold=cfg("WAKE_GATE_MIN_DBFS", "-48", float),
                    max_threshold=cfg("WAKE_GATE_MAX_DBFS", "-18", float))


def record_event(path, stamp):
    """Timestamps only. No audio, no transcript, by design."""
    p = pathlib.Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(stamp + "\n")


def main():
    from abbes_config import cfg, flag, listing

    tally = None
    if "--tally" in sys.argv:
        tally = sys.argv[sys.argv.index("--tally") + 1]
    elif flag("WAKE_TALLY_ENABLED"):
        tally = cfg("WAKE_TALLY")

    print("loading model...", flush=True)
    started = time.monotonic()
    listener = build(cfg, listing)
    print(f"ready in {time.monotonic() - started:.1f}s — gate at "
          f"{listener.threshold:g} dBFS, {len(json.loads(listener.detector.grammar))} grammar words",
          flush=True)
    if tally:
        print(f"tallying trigger timestamps to {tally}", flush=True)
    print("say the name. ctrl-c to stop.", flush=True)

    stream = MicStream(cfg("MIC_SOURCE"), cfg("WAKE_PREROLL_SECS", "1.2", float))
    count = 0
    began = time.monotonic()
    try:
        while True:
            chunk = stream.read()
            if chunk is None:
                continue
            hit = listener.feed(chunk)
            if not hit:
                continue
            count += 1
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            print(f"[{stamp}] TRIGGER #{count}: {hit}", flush=True)
            if tally:
                record_event(tally, stamp)
    except KeyboardInterrupt:
        mins = (time.monotonic() - began) / 60
        print(f"\n{count} triggers in {mins:.1f} min "
              f"({count / mins if mins else 0:.1f}/min), decoder ran {listener.duty * 100:.0f}% of the time",
              flush=True)
    finally:
        stream.close()


if __name__ == "__main__":
    main()
