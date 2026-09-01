#!/usr/bin/env python3
"""Voice loop for Abbes: wake word -> record -> transcribe -> ask -> speak."""

import array
import contextlib
import json
import math
import os
import re
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import abbes_match
import abbes_wake
from abbes_announce import AnnounceListener, announce_url
from abbes_camera import Camera, CameraPoller, frame_url
from abbes_satellite import SatelliteWake, wake_url
from abbes_audio import RATE, MicGone, MicStream, rms_dbfs, write_tone
from abbes_config import cfg, flag, listing
from abbes_stream import PlaybackStream, stream_turn

# tmpfs on this host, so a clip never reaches the SD card even for an instant.
RECORD_DIR = tempfile.gettempdir()

# Spoken by the Pi itself, not by the model, so they are set here rather than in
# the prompt. فصحى, to match what Abbes now answers in.
FAILURE_PHRASE = cfg("FAILURE_PHRASE", "لا أستطيع الإجابة الآن")
ACK_PHRASE = cfg("ACK_PHRASE", "لحظة")
PROMPT_PHRASE = cfg("PROMPT_PHRASE", "نعم؟")
RECONNECT_PHRASE = cfg("RECONNECT_PHRASE", "عاد الاتصال")


class Unreachable(Exception):
    pass


# Set once the wake listener exists. Everything that compares audio against a
# level reads it from here, so the gate, the end-of-speech detector and the
# trimmer all move together when the room changes -- which it does by 12 dB
# between 3am and 4pm on this microphone.
ROOM = {"floor": None}


def threshold_for(name, default, above_floor):
    """A threshold, preferring one derived from the measured room.

    Falls back to the configured absolute value when the floor is not known yet
    (the first seconds after start) or when adaptation is switched off.
    """
    floor = ROOM.get("floor")
    if floor is None:
        return cfg(name, default, float)
    return floor + above_floor


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def record_until_silence(stream, path, start_window, preroll=b""):
    """Record from the shared stream until the speaker stops. `preroll` is the
    audio captured just before the trigger fired, so a request spoken in the
    same breath as the name is not clipped."""
    chunk_ms = 100
    silence_limit = cfg("VAD_SILENCE_SECS", "1.5", float)
    # 10 dB over the floor: high enough that room noise counts as silence and the
    # recording actually ends, low enough that ordinary speech clears it.
    threshold = threshold_for("VAD_THRESHOLD_DBFS", "-28", cfg("VAD_ABOVE_FLOOR_DB", "6", float))
    max_secs = cfg("VAD_MAX_SECS", "15", float)
    min_secs = cfg("VAD_MIN_SECS", "1.0", float)
    # 0.5s was long enough to miss "نعم". The follow-up window exists precisely
    # for one-word answers, and a yes is about 0.3s: the level reached -15 dBFS,
    # far above threshold, and still failed to arm because it did not last.
    # A door or a click is under 100ms, so 0.3 still discriminates.
    min_speech = cfg("VAD_MIN_SPEECH_SECS", "0.3", float)

    frames = bytearray(preroll)
    levels = []
    silent_for = 0.0
    voiced_for = 0.0
    started = time.monotonic()
    heard = False
    while True:
        buf = stream.read()
        elapsed = time.monotonic() - started
        if buf is None:
            if elapsed >= max_secs or (not heard and elapsed >= start_window):
                break
            continue
        frames += buf
        level = rms_dbfs(buf)
        levels.append(level)
        if level > threshold:
            voiced_for += chunk_ms / 1000.0
            silent_for = 0.0
            # A click or a door is not speech; require sustained level before arming.
            if voiced_for >= min_speech:
                heard = True
        else:
            silent_for += chunk_ms / 1000.0
            if not heard:
                voiced_for = 0.0
        if heard and silent_for >= silence_limit and elapsed >= min_secs:
            break
        if not heard and elapsed >= start_window:
            break
        if elapsed >= max_secs:
            break

    if not heard:
        # The most common failure is a threshold above the speech it is meant to
        # detect, and until now that was indistinguishable in the log from a
        # genuinely empty room. Say which it was.
        if levels:
            ordered = sorted(levels)
            log(f"  no speech: threshold {threshold:.1f} dBFS, heard "
                f"p50 {ordered[len(ordered)//2]:.1f} p90 {ordered[int(len(ordered)*0.9)]:.1f} "
                f"max {ordered[-1]:.1f} over {len(levels)} windows")
        return None

    if levels:
        ordered = sorted(levels)
        log(f"  levels: threshold {threshold:.1f} dBFS, p50 {ordered[len(ordered)//2]:.1f} "
            f"p90 {ordered[int(len(ordered)*0.9)]:.1f} max {ordered[-1]:.1f}")

    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    return normalize(path)


def normalize(path):
    """Report the recorded level, and optionally apply makeup gain.

    Gain is off by default. The Derja STT endpoint is unaffected across a 25dB
    range, and the same boost measurably hurt whisper on identical audio, so
    raising a quiet recording buys nothing and can cost accuracy.
    """
    with wave.open(str(path)) as w:
        rate, n = w.getframerate(), w.getnframes()
        a = array.array("h")
        a.frombytes(w.readframes(n))
    if not a:
        return path
    peak = max(abs(x) for x in a)
    rms = math.sqrt(sum(float(x) * x for x in a) / len(a))
    db = lambda v: 20 * math.log10(v / 32768.0) if v > 0 else -120.0
    level = f"{n / rate:.1f}s, rms {db(rms):.1f} dBFS, peak {db(peak):.1f} dBFS"

    if rms <= 0 or not flag("AUDIO_NORMALIZE", False):
        log(f"recorded {level}")
        return trim_silence(path, rate, a, db)

    gain = min(20.0, (10 ** (-24 / 20) * 32768) / rms)
    if peak * gain > 32000:
        gain = 32000 / peak
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(array.array("h", [max(-32768, min(32767, int(x * gain))) for x in a]).tobytes())
    log(f"recorded {level}, normalized x{gain:.2f}")
    return path


def trim_silence(path, rate, samples, db):
    """Cut leading and trailing near-silence before the clip goes to Vosk.

    A recording that is three seconds of speech inside twenty of room noise
    transcribes as one word or nothing at all: the decoder spends its search on
    the noise. Trimming is not gain — every remaining sample is untouched — so it
    does not run into the makeup-gain problem that broke Derja recognition.
    """
    if not flag("AUDIO_TRIM", True) or not samples:
        return path
    win = max(1, int(rate * 0.05))
    margin = cfg("AUDIO_TRIM_MARGIN_SECS", "0.25", float)
    # 6 dB over the floor. A 12.4s recording of a short question transcribed as
    # one wrong word because most of it was room noise and the decoder spent its
    # search there; trimming to what is actually above the room fixes that
    # without touching a single remaining sample.
    floor = threshold_for("AUDIO_TRIM_DBFS", "-32", cfg("TRIM_ABOVE_FLOOR_DB", "6", float))

    loud = []
    for i in range(0, len(samples) - win, win):
        seg = samples[i:i + win]
        r = math.sqrt(sum(float(x) * x for x in seg) / len(seg))
        if db(r) > floor:
            loud.append(i)
    if not loud:
        return path

    start = max(0, loud[0] - int(margin * rate))
    end = min(len(samples), loud[-1] + win + int(margin * rate))
    kept = end - start
    if kept >= len(samples) - rate:      # nothing worth cutting
        return path

    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples[start:end].tobytes())
    log(f"  trimmed to {kept / rate:.1f}s of {len(samples) / rate:.1f}s")
    return path


def multipart(fields, filepath, filefield="file"):
    boundary = uuid.uuid4().hex
    body = bytearray()
    for k, v in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{filefield}\"; filename=\"a.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode()
    body += pathlib.Path(filepath).read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


NOISE_LABEL = re.compile(r"^\s*[\(\[\*][^)\]*]{0,40}[\)\]\*][\s.]*$")


def clean_transcript(text):
    """Drop whisper's non-speech annotations: (موسيقى), [Music], *soupir*."""
    kept = [ln for ln in text.splitlines() if ln.strip() and not NOISE_LABEL.match(ln)]
    return "\n".join(kept).strip()


def transcribe(path):
    url = cfg("WHISPER_URL")
    if not url:
        raise Unreachable("WHISPER_URL not configured")
    fields = {"language": cfg("WHISPER_LANGUAGE", "ar"), "response_format": "json"}
    prompt = cfg("WHISPER_PROMPT")
    if prompt:
        fields["prompt"] = prompt
    body, ctype = multipart(fields, path)
    req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=cfg("WHISPER_TIMEOUT", "60", float)) as r:
            return (json.loads(r.read()).get("text") or "").strip()
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as e:
        raise Unreachable(f"whisper: {e}") from e


def ask_gateway(text):
    mode = cfg("GATEWAY_MODE", "echo")
    timeout = cfg("GATEWAY_TIMEOUT", "90", float)
    if mode == "echo":
        return f"سمعتك تقول: {text}"
    if mode == "ssh":
        host = cfg("GATEWAY_SSH_HOST")
        user = cfg("GATEWAY_SSH_USER", "openclaw")
        key = cfg("GATEWAY_SSH_KEY", str(pathlib.Path.home() / ".ssh" / "id_ed25519_tunnel"))
        if not host:
            raise Unreachable("GATEWAY_SSH_HOST not configured")
        cmd = ["ssh", "-i", key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", f"{user}@{host}"]
        remote = cfg("GATEWAY_SSH_COMMAND")
        if remote:
            cmd.append(remote)
        try:
            out = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            # Never retry: the gateway may still complete an accepted turn, and a repeat could write twice.
            raise Unreachable("gateway ssh timeout") from e
        if out.returncode != 0:
            raise Unreachable(f"gateway ssh rc={out.returncode}: {out.stderr.strip()[:120]}")
        return out.stdout.strip()
    if mode == "http":
        url = cfg("GATEWAY_URL")
        if not url:
            raise Unreachable("GATEWAY_URL not configured")
        payload = json.dumps({"message": text}).encode()
        headers = {"Content-Type": "application/json"}
        token = cfg("GATEWAY_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=payload, headers=headers), timeout=timeout) as r:
                data = json.loads(r.read())
        except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as e:
            raise Unreachable(f"gateway: {e}") from e
        for key in ("reply", "text", "content", "message"):
            if isinstance(data.get(key), str):
                return data[key].strip()
        raise Unreachable("gateway: no reply field in response")
    raise Unreachable(f"unknown GATEWAY_MODE={mode}")


FRENCH_HINTS = {"le", "la", "les", "je", "tu", "vous", "est", "une", "des", "pour", "avec", "bonjour", "merci", "heure", "aujourd"}


def voice_for(text):
    arabic = sum(1 for ch in text if "؀" <= ch <= "ۿ")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    if arabic >= latin:
        return cfg("PIPER_VOICE_AR", "ar_JO-kareem-medium")
    words = {w.strip(".,!?;:").lower() for w in text.split()}
    if words & FRENCH_HINTS or any(c in text for c in "éèêàçùôî"):
        return cfg("PIPER_VOICE_FR", "fr_FR-siwis-medium")
    return cfg("PIPER_VOICE_EN", "en_US-lessac-medium")


def synth_remote(text, voice, out):
    url = cfg("PIPER_URL")
    if not url:
        raise Unreachable("no PIPER_URL")
    if not text.strip():
        raise Unreachable("empty text")
    payload = json.dumps({"text": text, "voice": voice}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=cfg("PIPER_TIMEOUT", "30", float)) as r:
            data = r.read()
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise Unreachable(f"piper remote: {e}") from e
    if not data.startswith(b"RIFF"):
        raise Unreachable("piper remote: not WAV")
    pathlib.Path(out).write_bytes(data)
    return out


def synth_local(text, voice, out):
    piper_dir = pathlib.Path(cfg("PIPER_DIR", str(pathlib.Path.home() / "piper")))
    binary = piper_dir / "piper"
    model = piper_dir / "voices" / f"{voice}.onnx"
    if not binary.is_file() or not model.is_file():
        raise Unreachable(f"local piper missing ({binary} / {model.name})")
    cmd = [str(binary), "--model", str(model), "--output_file", str(out)]
    tashkeel = piper_dir / "libtashkeel_model.ort"
    # espeak-ng handles only fully diacritized Arabic; without this it guesses the
    # short vowels. The remote Piper applies this by default, the local one does not.
    if tashkeel.is_file():
        cmd += ["--tashkeel_model", str(tashkeel)]
    env = dict(os.environ, LD_LIBRARY_PATH=str(piper_dir))
    try:
        subprocess.run(cmd, input=text, text=True, env=env, capture_output=True,
                       timeout=cfg("PIPER_LOCAL_TIMEOUT", "120", float), check=True)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        raise Unreachable(f"local piper: {e}") from e
    return out


def warm_remote():
    for voice in (cfg("PIPER_VOICE_FR"), cfg("PIPER_VOICE_EN")):
        try:
            synth_remote("ok", voice, pathlib.Path(tempfile.gettempdir()) / "abbes-warm.wav")
        except Unreachable:
            return
    (pathlib.Path(tempfile.gettempdir()) / "abbes-warm.wav").unlink(missing_ok=True)


def synthesize(text, voice, out):
    try:
        started = time.monotonic()
        synth_remote(text, voice, out)
        log(f"tts remote {voice} in {time.monotonic() - started:.1f}s")
        return out
    except Unreachable as e:
        log(f"tts remote unavailable ({e}); falling back to local piper")
    started = time.monotonic()
    synth_local(text, voice, out)
    log(f"tts local {voice} in {time.monotonic() - started:.1f}s")
    return out


def play_cmd(path):
    cmd = ["pw-play"]
    sink = cfg("SPEAKER_SINK")
    if sink:
        cmd += [f"--target={sink}"]
    cmd.append(str(path))
    return cmd


def wav_secs(path):
    try:
        with wave.open(str(path)) as w:
            return w.getnframes() / w.getframerate()
    except (wave.Error, OSError):
        return 0.0


def play(path):
    """Blocks until the audio has actually been heard.

    pw-play can return once the sink has accepted the samples, which over
    Bluetooth is well before the speaker has emitted them.
    """
    started = time.monotonic()
    subprocess.run(play_cmd(path), capture_output=True, timeout=cfg("PLAY_TIMEOUT", "120", float))
    remaining = wav_secs(path) - (time.monotonic() - started)
    if remaining > 0:
        time.sleep(remaining)


@contextlib.contextmanager
def muted(stream):
    """Hard-mute the microphone across playback so Abbes cannot hear itself.

    The tail covers Bluetooth latency: pw-play returns before the speaker has
    finished emitting the audio it was handed.
    """
    stream.mute()
    try:
        yield
    finally:
        time.sleep(cfg("WAKE_MUTE_TAIL_SECS", "1.5", float))
        stream.unmute()


def tone_wav():
    path = pathlib.Path.home() / ".cache" / "voicepi" / "trigger.wav"
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        write_tone(path)
    return path


def play_async(path):
    return subprocess.Popen(play_cmd(path), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cached_phrase(name, phrase, local_only=False):
    cache = pathlib.Path.home() / ".cache" / "voicepi" / f"{name}.wav"
    if cache.is_file():
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    voice = cfg("PIPER_VOICE_AR", "ar_JO-kareem-medium")
    if not local_only:
        try:
            return synth_remote(phrase, voice, cache)
        except Unreachable:
            pass
    return synth_local(phrase, voice, cache)


def failure_wav():
    # Local only: the degradation path must not depend on the network it is reporting broken.
    return cached_phrase("failure", FAILURE_PHRASE, local_only=True)


def ack_wav():
    return cached_phrase("ack", ACK_PHRASE)


def prompt_wav():
    return cached_phrase("prompt", PROMPT_PHRASE)


def reconnect_wav():
    # Local only, for the same reason as the failure phrase: this is what gets
    # said after the link to the machine that renders speech has been down.
    return cached_phrase("reconnect", RECONNECT_PHRASE, local_only=True)


def speak_failure():
    try:
        play(failure_wav())
    except Exception as e:
        log(f"could not speak failure phrase: {e}")


def log_turn(transcript, reply):
    path = pathlib.Path(cfg("TURN_LOG", str(pathlib.Path.home() / ".local" / "state" / "voicepi" / "turns.jsonl")))
    path.parent.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - 2 * 3600
    kept = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                if json.loads(line).get("ts", 0) >= cutoff:
                    kept.append(line)
            except json.JSONDecodeError:
                continue
    kept.append(json.dumps({"ts": time.time(), "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "transcript": transcript, "reply": reply}, ensure_ascii=False))
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    path.chmod(0o600)


def streamed_turn(url, wav_path):
    """One turn through the orchestrator: recording in, speech out as it renders.

    Returns "handled" when the turn ran, "empty" when nothing was actually said
    (the caller returns to idle quietly and may prompt), and "unreachable" when
    the orchestrator could not be contacted at all, so the caller can fall back to
    the direct path rather than leaving the household with silence.

    The acknowledgement tone goes through the same playback stream as the reply,
    so the two cannot overlap and the Bluetooth sink opens exactly once per turn.
    """
    player = PlaybackStream(sink=cfg("SPEAKER_SINK"), log=log)
    heard = {"text": ""}
    words = ",".join(x for x in (cfg("WAKE_CANDIDATES", ""), cfg("WAKE_WORDS", "")) if x)

    def note(t):
        heard["text"] = t
        log(f"TRANSCRIPT: {t}")

    try:
        try:
            player.write_wav(ack_wav().read_bytes())
        except Exception as e:
            log(f"ack unavailable: {e}")
        out = stream_turn(url, wav_path, player,
                          timeout=cfg("ORCHESTRATOR_TIMEOUT", "180", float),
                          trigger_words=words, on_transcript=note, log=log)
    except Unreachable as e:
        player.flush()
        log(f"FAILED: {e}")
        if str(e).startswith("orchestrator:"):
            return "unreachable"
        log_turn(heard["text"], "")
        speak_failure()
        return "handled"
    finally:
        player.close()

    reply = out.get("reply", "")
    marks = out.get("marks", {})
    if not heard["text"].strip():
        return "empty"
    log(f"REPLY: {reply}")
    if marks:
        log(f"  stt {marks.get('sttMs')}ms  first-token {marks.get('firstDeltaMs')}ms  "
            f"first-audio {marks.get('firstAudioMs')}ms  total {marks.get('totalMs')}ms")
    log_turn(heard["text"], reply)
    if not reply:
        # Something was said and the agent produced nothing. That is a real
        # failure and worth saying out loud.
        speak_failure()
    return "handled"


def one_turn(stream, preroll=b"", start_window=None):
    """Record and answer one request.

    Returns True when something was actually said. Room noise returns False, so
    a noisy room cannot keep re-opening the follow-up window forever.

    The recording is unlinked in a `finally` covering the whole turn, so it goes
    whether transcription succeeded, failed, or threw.
    """
    if start_window is None:
        start_window = cfg("VAD_START_SECS", "10", float)
    tmp = pathlib.Path(RECORD_DIR) / f"abbes-{uuid.uuid4().hex}.wav"
    try:
        log("listening...")
        if record_until_silence(stream, tmp, start_window, preroll) is None:
            log("no speech detected, back to idle")
            return False

        orch = cfg("ORCHESTRATOR_URL")
        if orch:
            with muted(stream):
                status = streamed_turn(orch, tmp)
            if status == "handled":
                return True
            if status == "empty":
                # Nothing was actually said. Return to idle quietly so the caller
                # can prompt; speaking the failure phrase here is what made Abbes
                # repeat "ما نجمش نجاوبك توة" at an empty room.
                log("nothing but noise, back to idle")
                return False
            log("orchestrator unreachable, falling back to the direct path")

        with muted(stream):
            try:
                transcript = transcribe(tmp)
            except Unreachable as e:
                log(f"FAILED: {e}")
                speak_failure()
                return True
            finally:
                tmp.unlink(missing_ok=True)

            cleaned = clean_transcript(transcript)
            if cleaned != transcript:
                log(f"stripped noise labels: {transcript!r} -> {cleaned!r}")
            transcript = cleaned
            if not transcript:
                log("nothing but noise, back to idle")
                return False
            log(f"TRANSCRIPT: {transcript}")

            spoken = MATCHER.strip(transcript) if MATCHER else transcript
            if spoken != transcript:
                log(f"stripped trigger word: {spoken!r}")
            if not spoken:
                log("only the name, nothing asked")
                return True

            ack = None
            try:
                ack = play_async(ack_wav())
            except Exception as e:
                log(f"ack unavailable: {e}")

            try:
                reply = ask_gateway(spoken)
            except Unreachable as e:
                log(f"FAILED: {e}")
                log_turn(spoken, "")
                speak_failure()
                return True

            log(f"REPLY: {reply}")
            log_turn(spoken, reply)
            if not reply:
                return True

            out = pathlib.Path(RECORD_DIR) / f"abbes-tts-{uuid.uuid4().hex}.wav"
            try:
                synthesize(reply, voice_for(reply), out)
                if ack is not None:
                    ack.wait(timeout=10)
                play(out)
            except Unreachable as e:
                log(f"FAILED: {e}")
                speak_failure()
            finally:
                out.unlink(missing_ok=True)
        return True
    finally:
        tmp.unlink(missing_ok=True)


def _preroll_has_speech(preroll):
    """True when the request was spoken in the same breath as the name.

    The pre-roll holds the audio captured just before the trigger fired. If it
    carries speech, the question is already in hand and prompting would talk over
    someone mid-sentence.
    """
    if not preroll:
        return False
    threshold = cfg("VAD_THRESHOLD_DBFS", "-30", float)
    tail = preroll[-RATE * 2 * 2:] if len(preroll) > 4 else preroll
    return rms_dbfs(tail) > threshold


def conversation(stream, preroll):
    """Answer the name, then wait for the question however long it takes.

    Hearing the name is not the same as being asked something. Abbes says "نعم؟"
    as soon as it is called, then holds the microphone open until you actually
    start speaking -- two seconds or thirty, it does not matter -- and only stops
    recording when you stop. A request that arrives in the same breath as the name
    is caught by the pre-roll and answered without the prompt.
    """
    followup = cfg("WAKE_FOLLOWUP_SECS", "10", float)
    can_prompt = flag("WAKE_PROMPT", True)
    window = cfg("WAKE_REQUEST_SECS", "1.5", float) if can_prompt else None

    # If the name arrived alone, answer it before listening rather than after a
    # silent pause -- from the room, silence is indistinguishable from not having
    # been heard.
    if can_prompt and not _preroll_has_speech(preroll):
        log(f"name heard; answering {PROMPT_PHRASE} and waiting for the question")
        try:
            with muted(stream):
                play(prompt_wav())
        except Exception as e:
            log(f"prompt unavailable: {e}")
        can_prompt = False
        preroll = b""
        window = cfg("WAKE_PROMPT_SECS", "30", float)

    while True:
        if one_turn(stream, preroll, window):
            preroll = b""
            can_prompt = False
            if followup <= 0:
                return
            window = followup
            log(f"follow-up window: {followup:g}s, no name needed")
            continue
        if not can_prompt:
            return
        can_prompt = False
        preroll = b""
        log(f"name with no request; asking {PROMPT_PHRASE}")
        try:
            with muted(stream):
                play(prompt_wav())
        except Exception as e:
            log(f"prompt unavailable: {e}")
            return
        window = cfg("WAKE_PROMPT_SECS", "8", float)


def sweep_recordings():
    """Delete clips orphaned by a crash or a restart mid-turn.

    The turn's own `finally` cannot run if the process is killed between
    recording and transcription, so startup clears anything left behind.
    """
    stale = list(pathlib.Path(RECORD_DIR).glob("abbes-*.wav"))
    for f in stale:
        f.unlink(missing_ok=True)
    if stale:
        log(f"removed {len(stale)} orphaned recording(s) from a previous run")


def watch_fifo(event):
    fifo = pathlib.Path(cfg("TRIGGER_FIFO", os.environ.get("XDG_RUNTIME_DIR", "/tmp") + "/abbes-trigger"))
    if not fifo.is_fifo():
        fifo.unlink(missing_ok=True)
        os.mkfifo(fifo, 0o600)
    def run():
        while True:
            with open(fifo, "r") as f:
                f.read()
            event.set()
    threading.Thread(target=run, daemon=True).start()
    return fifo


MATCHER = None


def ensure_vosk():
    """Re-exec under the Vosk venv. The loop itself is stdlib-only; the venv
    exists solely to carry the wake-word dependency, so without it everything
    still runs, just without the wake word."""
    venv = cfg("WAKE_VOSK_PYTHON")
    if not venv or not flag("WAKE_ENABLED", True) or os.environ.get("ABBES_REEXEC"):
        return
    try:
        import vosk  # noqa: F401
    except ImportError:
        if pathlib.Path(venv).is_file():
            os.execve(venv, [venv, os.path.abspath(__file__)] + sys.argv[1:],
                      dict(os.environ, ABBES_REEXEC="1"))


def start_announce_listener(stream):
    """Attach the downlink, or explain why there is none and carry on.

    A missing announce link must never stop the Pi answering questions, so every
    failure here is logged and swallowed. Proactive speech is the extra.
    """
    if not flag("ANNOUNCE_ENABLED", True):
        log("announce: disabled")
        return None
    url = cfg("ORCHESTRATOR_URL")
    if not url:
        log("announce: no ORCHESTRATOR_URL, downlink off")
        return None

    def notice(gap_secs):
        log(f"announce: link was down {gap_secs:.0f}s, saying so")
        with muted(stream):
            player = PlaybackStream(sink=cfg("SPEAKER_SINK"), log=log)
            try:
                player.write_wav(reconnect_wav().read_bytes())
            finally:
                player.close()

    listener = AnnounceListener(
        announce_url(url),
        make_player=lambda: PlaybackStream(sink=cfg("SPEAKER_SINK"), log=log),
        mute_ctx=lambda: muted(stream),
        log=log,
        on_reconnect=notice,
        reconnect_notice_secs=cfg("RECONNECT_NOTICE_SECS", "120", float),
    )
    listener.start()
    return listener


def start_camera_poller():
    """Off unless CAMERA_ENABLED. Failing to see must never stop it hearing."""
    if not flag("CAMERA_ENABLED", False):
        return None
    url = cfg("ORCHESTRATOR_URL")
    if not url:
        log("camera: no ORCHESTRATOR_URL, eyes off")
        return None
    device = cfg("CAMERA_DEVICE", "/dev/video0")
    if not pathlib.Path(device).exists():
        log(f"camera: {device} is not present, eyes off")
        return None
    poller = CameraPoller(
        frame_url(url),
        Camera(device=device,
               width=cfg("CAMERA_WIDTH", "640", int),
               height=cfg("CAMERA_HEIGHT", "480", int),
               log=log),
        interval=cfg("CAMERA_INTERVAL_SECS", "3", float),
        log=log,
    )
    poller.start()
    return poller


def main():
    global MATCHER
    ensure_vosk()
    sweep_recordings()
    stream = MicStream(cfg("MIC_SOURCE"), cfg("WAKE_PREROLL_SECS", "1.2", float))

    listener = None
    satellite = None
    if flag("SATELLITE_WAKE", False):
        # The 267 MB acoustic model stays on the server. This end keeps the
        # energy gate, which is arithmetic, and streams what it hears.
        url = cfg("WAKE_SIDECAR_URL")
        if url:
            satellite = SatelliteWake(wake_url(url), log=log).start()
            MATCHER = abbes_match.Matcher(listing("WAKE_CANDIDATES") or
                                          abbes_match.DEFAULT_CANDIDATES,
                                          cfg("WAKE_FUZZ", "1", int))
            log(f"wake word is remote: {wake_url(url)}")
        else:
            log("WARNING: SATELLITE_WAKE set but WAKE_SIDECAR_URL is not; falling back")
    if satellite is None and flag("WAKE_ENABLED", True):
        try:
            started = time.monotonic()
            listener = abbes_wake.build(cfg, listing)
            MATCHER = listener.detector.matcher
            log(f"wake word ready in {time.monotonic() - started:.1f}s "
                f"(gate {listener.threshold:g} dBFS)")
        except Exception as e:
            log(f"WARNING: wake word unavailable ({e}); trigger manually")

    if "--once" in sys.argv:
        one_turn(stream)
        return

    for name, fn in (("failure phrase", failure_wav), ("ack phrase", ack_wav),
                     ("prompt phrase", prompt_wav), ("trigger tone", tone_wav)):
        try:
            fn()
            log(f"{name} cached")
        except Exception as e:
            log(f"WARNING: {name} not cached ({e})")
    warm_remote()

    manual = threading.Event()
    fifo = watch_fifo(manual)
    tally = cfg("WAKE_TALLY") if flag("WAKE_TALLY_ENABLED") else None
    play_tone = flag("WAKE_TONE", True)
    start_announce_listener(stream)
    start_camera_poller()
    log(f"idle. say the name{'' if listener else ' (wake word off)'}, or: echo go > {fifo}")

    while True:
        hit = None
        try:
            while not manual.is_set():
                chunk = stream.read()
                if chunk is None:
                    continue
                if satellite is not None:
                    satellite.feed(chunk)
                    hit = satellite.heard_name()
                elif listener is not None:
                    hit = listener.feed(chunk)
                    ROOM["floor"] = listener.noise_floor
                else:
                    continue
                if hit:
                    break
            if manual.is_set():
                manual.clear()
                hit = None
                log("triggered manually")
            else:
                log(f"TRIGGER: {hit}")
                if tally:
                    abbes_wake.record_event(tally, time.strftime("%Y-%m-%dT%H:%M:%S"))
        except MicGone as e:
            log(f"FATAL: {e}")
            raise

        preroll = stream.preroll()
        if hit and play_tone:
            # Async: the request is often already underway, so recording must
            # not wait on the speaker.
            try:
                play_async(tone_wav())
            except Exception as e:
                log(f"tone unavailable: {e}")
        try:
            conversation(stream, preroll)
        except MicGone:
            raise
        except Exception as e:
            log(f"turn crashed: {e}")
        if listener:
            listener.reset()
        manual.clear()
        log("idle.")


if __name__ == "__main__":
    main()
