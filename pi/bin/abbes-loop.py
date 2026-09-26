#!/usr/bin/env python3
"""Voice loop for Abbes: wake word -> tone -> record -> orchestrator -> speak.

The Pi does no speech processing beyond the wake word. The recording goes to the
orchestrator on the gateway host, which transcribes it, asks the agent and streams
the spoken reply back sentence by sentence.
"""

import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import wave

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import abbes_wake
from abbes_audio import RATE, MicGone, MicStream, rms_dbfs, write_tone
from abbes_config import cfg, flag, listing
from abbes_stream import PlaybackStream, Unreachable, stream_turn

# tmpfs on this host, so a clip never reaches the SD card.
RECORD_DIR = tempfile.gettempdir()
CACHE = pathlib.Path.home() / ".cache" / "voicepi"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def record_until_silence(stream, path, start_window, preroll=b""):
    """Record until the speaker stops. None if nobody started talking in time."""
    chunk_secs = 0.1
    threshold = cfg("VAD_THRESHOLD_DBFS", "-36", float)
    silence_limit = cfg("VAD_SILENCE_SECS", "1.2", float)
    max_secs = cfg("VAD_MAX_SECS", "20", float)
    min_speech = cfg("VAD_MIN_SPEECH_SECS", "0.3", float)

    frames = bytearray(preroll)
    peak = -120.0
    silent_for = voiced_for = 0.0
    heard = False
    started = time.monotonic()
    while True:
        elapsed = time.monotonic() - started
        if elapsed >= max_secs or (not heard and elapsed >= start_window):
            break
        buf = stream.read()
        if buf is None:
            continue
        frames += buf
        level = rms_dbfs(buf)
        peak = max(peak, level)
        if level > threshold:
            voiced_for += chunk_secs
            silent_for = 0.0
            heard = heard or voiced_for >= min_speech
        else:
            silent_for += chunk_secs
            if not heard:
                voiced_for = 0.0
        if heard and silent_for >= silence_limit:
            break

    if not heard:
        log(f"  no speech (threshold {threshold:g} dBFS, loudest {peak:.1f})")
        return None
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    log(f"  recorded {len(frames) / (RATE * 2):.1f}s (loudest {peak:.1f} dBFS)")
    return path


def tone(name, freqs):
    path = CACHE / f"{name}.wav"
    if not path.is_file():
        CACHE.mkdir(parents=True, exist_ok=True)
        write_tone(path, freqs=freqs)
    return path


def play(path, wait=True):
    cmd = ["pw-play"]
    if cfg("SPEAKER_SINK"):
        cmd.append(f"--target={cfg('SPEAKER_SINK')}")
    proc = subprocess.Popen(cmd + [str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if wait:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def error_tone():
    play(tone("error", (440, 330)))


def turn(stream, preroll, start_window):
    """Record one request and speak the answer. False if nothing was said."""
    clip = pathlib.Path(RECORD_DIR) / f"abbes-{uuid.uuid4().hex}.wav"
    try:
        log("listening...")
        if record_until_silence(stream, clip, start_window, preroll) is None:
            return False

        heard = {"text": ""}

        def on_transcript(text):
            heard["text"] = text
            log(f"HEARD: {text!r}")

        player = PlaybackStream(sink=cfg("SPEAKER_SINK"), log=log)
        try:
            out = stream_turn(cfg("ORCHESTRATOR_URL"), clip, player,
                              timeout=cfg("ORCHESTRATOR_TIMEOUT", "180", float),
                              on_transcript=on_transcript, log=log)
        except Unreachable as e:
            player.flush()
            log(f"FAILED: {e}")
            error_tone()
            return True

        if not heard["text"]:
            log("  nothing but noise")
            return False
        marks = out.get("marks") or {}
        log(f"REPLY: {out.get('reply', '')!r}  stt {marks.get('sttMs')}ms "
            f"first-audio {marks.get('firstAudioMs')}ms total {marks.get('totalMs')}ms")
        if not out.get("reply"):
            log(f"  no reply ({out.get('error', 'empty')})")
            error_tone()
        return True
    finally:
        clip.unlink(missing_ok=True)


def conversation(stream, preroll):
    """Answer, then keep listening briefly so a follow-up needs no name."""
    window = cfg("VAD_START_SECS", "8", float)
    followup = cfg("WAKE_FOLLOWUP_SECS", "8", float)
    while turn(stream, preroll, window) and followup > 0:
        stream.drain()
        preroll = b""
        window = followup
        log(f"follow-up window {followup:g}s")


def watch_fifo(event):
    """`echo go > $XDG_RUNTIME_DIR/abbes-trigger` starts a turn without the name."""
    fifo = pathlib.Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "abbes-trigger"
    if not fifo.is_fifo():
        fifo.unlink(missing_ok=True)
        os.mkfifo(fifo, 0o600)

    def run():
        while True:
            with open(fifo) as f:
                f.read()
            event.set()

    threading.Thread(target=run, daemon=True).start()
    return fifo


def ensure_vosk():
    """Re-exec under the Vosk venv; the wake word is the only non-stdlib dependency."""
    venv = cfg("WAKE_VOSK_PYTHON")
    if not venv or os.environ.get("ABBES_REEXEC"):
        return
    try:
        import vosk  # noqa: F401
    except ImportError:
        if pathlib.Path(venv).is_file():
            os.execve(venv, [venv, os.path.abspath(__file__)] + sys.argv[1:],
                      dict(os.environ, ABBES_REEXEC="1"))


def main():
    ensure_vosk()
    for stale in pathlib.Path(RECORD_DIR).glob("abbes-*.wav"):
        stale.unlink(missing_ok=True)
    if not cfg("ORCHESTRATOR_URL"):
        sys.exit("ORCHESTRATOR_URL is not set in voicepi.env")

    stream = MicStream(cfg("MIC_SOURCE"), cfg("WAKE_PREROLL_SECS", "1.2", float))
    listener = None
    if flag("WAKE_ENABLED", True):
        started = time.monotonic()
        listener = abbes_wake.build(cfg, listing)
        log(f"wake word ready in {time.monotonic() - started:.1f}s (gate {listener.threshold:g} dBFS)")

    if "--once" in sys.argv:
        conversation(stream, b"")
        return

    manual = threading.Event()
    fifo = watch_fifo(manual)
    trigger = tone("trigger", (880, 1320))
    log(f"idle. say the name, or: echo go > {fifo}")

    while True:
        hit = None
        while not manual.is_set() and not hit:
            chunk = stream.read()
            if chunk is not None and listener is not None:
                hit = listener.feed(chunk)
        manual.clear()
        log(f"TRIGGER: {hit or 'manual'}")

        preroll = stream.preroll() if hit else b""
        play(trigger, wait=False)
        try:
            conversation(stream, preroll)
        except MicGone:
            raise
        except Exception as e:
            log(f"turn crashed: {e}")
            error_tone()
        if listener:
            listener.reset()
        stream.drain()
        log("idle.")


if __name__ == "__main__":
    try:
        main()
    except MicGone as e:
        # A wedged USB controller takes every audio device with it; only a reboot
        # cures it. Exit and let systemd back off. See pi/README.md.
        log(f"FATAL: {e}. If this repeats, check `journalctl -k | grep NYET`.")
        sys.exit(1)
