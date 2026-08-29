# Implementation prompt — add a Piper TTS server to `intel-gpu-inference`

Paste everything below to the agent that owns the `intel-gpu-inference` repository.

---

## Goal

Add **Piper** (neural text-to-speech) as a fifth service in this stack, exposed over HTTP
on the LAN, following the exact conventions already used by `whisper-server`.

A Raspberry Pi 3B on the LAN is the consumer. It currently runs Piper locally and it is
too slow: **~9.6s wall to synthesise a ~2.3s Arabic sentence (RTF ≈ 4.2)**. Measured on
that Pi, and ruled out as causes: model-load overhead (several sentences through one
process still show ~9.4s gaps), voice quality (`low` is within 3% of `medium`), and thread
count (`OMP_NUM_THREADS=1` vs `4` differ by <2%). The Cortex-A53 is simply the limit.
Moving synthesis to this host is the fix.

## What already exists — match these patterns exactly

| Convention | Existing example |
|---|---|
| Service template at repo root | `whisper-server.service.template` |
| Install script | `scripts/install-whisper.sh` |
| Launch script | `scripts/run-whisper.sh` |
| Test script | `scripts/test-whisper.sh` |
| Install flag | `./install.sh --with-whisper` (add `--with-piper`, include in `--all`) |
| Config | appended to `~/.config/intel-gpu-inference/env` |
| Staggered startup | `scripts/wait-for-model-load.sh <unit>:<port>` in `ExecStartPre` |
| Docs | an "Exposed Services" section in `AGENTS.md` |

Ports in use: **8080** llama-server, **8085** embedding-server, **9090** whisper-server,
**3000** open-websearch. Use **9091** for Piper.

## Deliverables

1. `piper-server.service.template`
2. `scripts/install-piper.sh` — supports `--update` and `--no-service`, like the whisper one
3. `scripts/run-piper.sh`
4. `scripts/test-piper.sh`
5. `install.sh` — add `--with-piper`, and include it in `--all`
6. `AGENTS.md` — document the service, endpoints, and a working `curl` example

## Upstream

Use **[OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl)** (v1.6.0+). Note
`rhasspy/piper` went read-only in October 2025 — do not build from it. Also note the
Debian package named `piper` is an unrelated gaming-mouse configurator.

It ships an HTTP server: `python3 -m piper.http_server --host 0.0.0.0 --port 9091 -m <voice>`.
Install into a dedicated venv under the project directory; do not touch system Python.

## API contract the consumer depends on

- `POST /` — JSON body, `Content-Type: application/json`
- Request fields: `text` (required), `voice` (optional, e.g. `ar_JO-kareem-medium`),
  `length_scale` (optional, <1.0 faster)
- Response: **WAV audio bytes**
- A `GET` endpoint listing available voices
- Bind `0.0.0.0` so the LAN can reach it, as the other services do

## Voices — install all three

From `https://huggingface.co/rhasspy/piper-voices/resolve/main/<path>/<name>.{onnx,onnx.json}`

| Voice | Path | Note |
|---|---|---|
| `ar_JO-kareem-medium` | `ar/ar_JO/kareem/medium` | **primary — Arabic is the target language** |
| `fr_FR-siwis-medium` | `fr/fr_FR/siwis/medium` | |
| `en_US-lessac-medium` | `en/en_US/lessac/medium` | |

Each is ~61MB. Put them in `$MODELS_DIR/piper/`, consistent with `MODELS_DIR` in the env
file. The server must be able to serve **all three without restarting** — the consumer
picks a voice per request based on the script of the reply text.

## Memory — read this before choosing defaults

This host is an **LXC container**, which makes its limits easy to misread:

- `/proc/meminfo` is lxcfs-filtered. It reports the container's **limit** (10GB) as though
  it were physical RAM.
- `journalctl -k` and `dmesg` are empty — a container has no kernel log. An OOM kill here
  is the container's cgroup limit enforced by the LXC host, and the report lands in the
  **host's** kernel log, not this one. Do not waste time adding users to `adm` or
  `systemd-journal`; it cannot surface it.
- Current headroom: 10GB RAM + 10GB swap. The swap was raised from 2GB **specifically
  because whisper-server was being OOM-killed on every transcription request**. Do not
  assume that headroom is spare — it is already spoken for.
- `whisper-server.service` sets `OOMScoreAdjust=900`, deliberately making it the first
  process killed under pressure.

Therefore:

- Give `piper-server.service` an explicit **`MemoryMax=`** (measure the steady-state RSS
  first, then set roughly 1.5x) so a leak cannot take the box down.
- Set **`OOMScoreAdjust`** so Piper is sacrificed before `llama-server` (which holds Gemma
  12B and must not be disturbed). A value between whisper's 900 and the default is
  reasonable — justify whatever you choose.
- Add Piper to the staggered startup via `wait-for-model-load.sh` so it does not contend
  with llama-server and embedding-server during their model loads.

## CPU or GPU

Piper is ONNX. The stock `onnxruntime` wheel is **CPU-only**, and on this host's CPU that
is very likely already far faster than real time — the Pi's problem was a 1.2GHz A53.
**Measure CPU-only first and report the RTF.** Only pursue an OpenVINO execution provider
on the Arc A770 if CPU RTF is above ~0.3, and weigh it against contending with llama.cpp
for the GPU. Do not default to GPU because the project name says GPU.

## Acceptance criteria

1. `./install.sh --with-piper` installs cleanly from a fresh checkout.
2. Service starts on boot, survives a reboot, and restarts on failure.
3. `scripts/test-piper.sh` passes: server listening, synthesis returns valid WAV, all three
   voices selectable, voice-list endpoint works.
4. **Report measured RTF per voice**, especially `ar_JO-kareem-medium`.
5. **Report steady-state and peak RSS**, and confirm `llama-server`, `embedding-server`,
   `whisper-server` and `open-websearch` are all still healthy afterwards.
6. `AGENTS.md` documents the service with a copy-pasteable `curl`.

## Do not

- Do not modify `llama-server`, `embedding-server`, `whisper-server`, or `open-websearch`.
- Do not add Piper settings to the shared env file in a way that changes the other four
  services — that file is read by all of them via `EnvironmentFile`.
- Do not introduce Wyoming, Home Assistant, or any voice framework. Plain HTTP only.
- Do not commit model files.
