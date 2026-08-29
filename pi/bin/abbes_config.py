"""Config shared by the loop and the wake detector: ~/.config/voicepi/voicepi.env."""

import os
import pathlib

PREFIXES = ("WHISPER_", "PIPER_", "GATEWAY_", "VAD_", "MIC_", "SPEAKER_",
            "TRIGGER_", "TURN_", "WAKE_", "PLAY_")

PATH = pathlib.Path.home() / ".config" / "voicepi" / "voicepi.env"


def load():
    values = {}
    if PATH.is_file():
        for line in PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            values[k.strip()] = v
    values.update({k: v for k, v in os.environ.items()
                   if k in values or k.startswith(PREFIXES)})
    return values


CFG = load()


def cfg(key, default=None, cast=str):
    v = CFG.get(key, default)
    if v is None:
        return None
    try:
        return cast(v)
    except (TypeError, ValueError):
        return default


def flag(key, default=False):
    v = CFG.get(key)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def listing(key, default=""):
    return [p.strip() for p in cfg(key, default).split("|") if p.strip()]
