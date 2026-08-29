#!/usr/bin/env python3
"""Voice loop for Abbes: trigger -> record -> transcribe -> ask -> speak."""

import array
import json
import math
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import wave

FAILURE_PHRASE = "ما نجمش نجاوبك توة"


class Unreachable(Exception):
    pass


def load_config():
    cfg = {}
    path = pathlib.Path.home() / ".config" / "voicepi" / "voicepi.env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    cfg.update({k: v for k, v in os.environ.items() if k in cfg or k.startswith(("WHISPER_", "PIPER_", "GATEWAY_", "VAD_", "MIC_", "SPEAKER_", "TRIGGER_", "TURN_"))})
    return cfg


CFG = load_config()


def cfg(key, default=None, cast=str):
    v = CFG.get(key, default)
    if v is None:
        return None
    try:
        return cast(v)
    except (TypeError, ValueError):
        return default


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def dbfs(v):
    return 20 * math.log10(v / 32768.0) if v > 0 else -120.0


def rms_of(buf):
    a = array.array("h")
    a.frombytes(buf[: len(buf) // 2 * 2])
    if not a:
        return 0.0
    return math.sqrt(sum(float(x) * x for x in a) / len(a))


def record_until_silence(path):
    rate = 16000
    chunk_ms = 100
    chunk_bytes = int(rate * 2 * chunk_ms / 1000)
    silence_limit = cfg("VAD_SILENCE_SECS", "1.5", float)
    threshold = cfg("VAD_THRESHOLD_DBFS", "-45", float)
    max_secs = cfg("VAD_MAX_SECS", "20", float)
    min_secs = cfg("VAD_MIN_SECS", "1.0", float)

    cmd = ["parecord", "--raw", f"--rate={rate}", "--channels=1", "--format=s16le"]
    source = cfg("MIC_SOURCE")
    if source:
        cmd += ["-d", source]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    frames = bytearray()
    silent_for = 0.0
    started = time.monotonic()
    heard = False
    try:
        while True:
            buf = proc.stdout.read(chunk_bytes)
            if not buf:
                break
            frames += buf
            level = dbfs(rms_of(buf))
            elapsed = time.monotonic() - started
            if level > threshold:
                heard = True
                silent_for = 0.0
            else:
                silent_for += chunk_ms / 1000.0
            if heard and silent_for >= silence_limit and elapsed >= min_secs:
                break
            if elapsed >= max_secs:
                break
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    if not heard:
        return None

    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return normalize(path)


def normalize(path):
    with wave.open(str(path)) as w:
        rate, n = w.getframerate(), w.getnframes()
        a = array.array("h")
        a.frombytes(w.readframes(n))
    if not a:
        return path
    peak = max(abs(x) for x in a)
    rms = math.sqrt(sum(float(x) * x for x in a) / len(a))
    if rms <= 0:
        return path
    gain = min(20.0, (10 ** (-24 / 20) * 32768) / rms)
    if peak * gain > 32000:
        gain = 32000 / peak
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(array.array("h", [max(-32768, min(32767, int(x * gain))) for x in a]).tobytes())
    log(f"recorded {n / rate:.1f}s, normalized x{gain:.2f}")
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
    env = dict(os.environ, LD_LIBRARY_PATH=str(piper_dir))
    try:
        subprocess.run([str(binary), "--model", str(model), "--output_file", str(out)],
                       input=text, text=True, env=env, capture_output=True,
                       timeout=cfg("PIPER_LOCAL_TIMEOUT", "120", float), check=True)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        raise Unreachable(f"local piper: {e}") from e
    return out


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


def play(path):
    cmd = ["pw-play"]
    sink = cfg("SPEAKER_SINK")
    if sink:
        cmd += [f"--target={sink}"]
    cmd.append(str(path))
    subprocess.run(cmd, capture_output=True, timeout=cfg("PLAY_TIMEOUT", "120", float))


def failure_wav():
    cache = pathlib.Path(cfg("FAILURE_WAV", str(pathlib.Path.home() / ".cache" / "voicepi" / "failure.wav")))
    if cache.is_file():
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    synth_local(FAILURE_PHRASE, cfg("PIPER_VOICE_AR", "ar_JO-kareem-medium"), cache)
    return cache


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


def one_turn():
    tmp = pathlib.Path(tempfile.gettempdir()) / f"abbes-{uuid.uuid4().hex}.wav"
    transcript = ""
    try:
        log("listening...")
        if record_until_silence(tmp) is None:
            log("no speech detected, back to idle")
            return
        transcript = transcribe(tmp)
    except Unreachable as e:
        log(f"FAILED: {e}")
        speak_failure()
        return
    finally:
        tmp.unlink(missing_ok=True)

    if not transcript:
        log("empty transcript, back to idle")
        return
    log(f"TRANSCRIPT: {transcript}")

    try:
        reply = ask_gateway(transcript)
    except Unreachable as e:
        log(f"FAILED: {e}")
        log_turn(transcript, "")
        speak_failure()
        return

    log(f"REPLY: {reply}")
    log_turn(transcript, reply)
    if not reply:
        return

    out = pathlib.Path(tempfile.gettempdir()) / f"abbes-tts-{uuid.uuid4().hex}.wav"
    try:
        synthesize(reply, voice_for(reply), out)
        play(out)
    except Unreachable as e:
        log(f"FAILED: {e}")
        speak_failure()
    finally:
        out.unlink(missing_ok=True)


def main():
    if "--once" in sys.argv:
        one_turn()
        return
    fifo = pathlib.Path(cfg("TRIGGER_FIFO", os.environ.get("XDG_RUNTIME_DIR", "/tmp") + "/abbes-trigger"))
    if not fifo.is_fifo():
        fifo.unlink(missing_ok=True)
        os.mkfifo(fifo, 0o600)
    try:
        failure_wav()
        log("failure phrase cached")
    except Exception as e:
        log(f"WARNING: failure phrase not cached ({e}) — degradation path will be slow")
    log(f"idle. trigger with: echo go > {fifo}")
    while True:
        with open(fifo, "r") as f:
            f.read()
        try:
            one_turn()
        except Exception as e:
            log(f"turn crashed: {e}")
        log("idle.")


if __name__ == "__main__":
    main()
