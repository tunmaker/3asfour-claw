"""Wake-word spotting without carrying the model.

The Pi held a 267 MB Vosk model to recognise one word, on a machine with 905 MB
of RAM. This streams the microphone to the wake sidecar instead and waits to be
told. Everything after the wake is unchanged: the Pi still records the request
and posts it to the orchestrator exactly as before.

Only the wake word moves. That is deliberate -- it is where all the memory was,
and it is the smallest change that recovers it.

The local energy gate stays here rather than moving too. It costs nothing, it
keeps the room's silence off the network, and it is the only thing that can tell
the difference between a quiet house and a dead link.

Stdlib only, like the rest of the Pi.
"""
import http.client
import json
import queue
import threading
import time
import urllib.parse

# Dropped rather than queued without bound: audio that is seconds late is worse
# than no audio, because a wake reported for something said ten seconds ago
# fires after the speaker has given up.
MAX_QUEUED_CHUNKS = 50


class SatelliteWake:
    """Streams microphone audio to the sidecar and reports what it heard back."""

    def __init__(self, url, log=lambda *a: None, reconnect_notice_secs=120,
                 on_reconnect=None):
        self.url = url
        self.log = log
        self.reconnect_notice_secs = reconnect_notice_secs
        self.on_reconnect = on_reconnect
        self._chunks = queue.Queue(maxsize=MAX_QUEUED_CHUNKS)
        self._wake = threading.Event()
        self._last_wake = None
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._down_since = None
        self.dropped = 0

    # ---------------------------------------------------------------- public

    def start(self):
        threading.Thread(target=self._run, name="satellite-wake", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()

    @property
    def connected(self):
        return self._connected.is_set()

    def feed(self, chunk):
        """Offer a chunk. Never blocks; a full queue means the link is stalled."""
        if not self._connected.is_set():
            return
        try:
            self._chunks.put_nowait(chunk)
        except queue.Full:
            self.dropped += 1
            if self.dropped % 100 == 1:
                self.log(f"satellite: uplink stalled, {self.dropped} chunks dropped")

    def heard_name(self):
        """True once per wake. Clears itself, like the manual trigger event."""
        if self._wake.is_set():
            self._wake.clear()
            return self._last_wake or True
        return None

    # --------------------------------------------------------------- private

    def _run(self):
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._session()
                backoff = 1.0
            except Exception as e:
                self._connected.clear()
                if self._down_since is None:
                    self._down_since = time.time()
                self.log(f"satellite: link down ({e}); retrying in {backoff:.0f}s")
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 60.0)

    def _session(self):
        parts = urllib.parse.urlsplit(self.url)
        conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=30)
        conn.putrequest("POST", parts.path or "/listen")
        conn.putheader("Content-Type", "application/octet-stream")
        conn.putheader("Transfer-Encoding", "chunked")
        conn.endheaders()

        # Drain anything buffered while disconnected: it describes a room that
        # has moved on.
        while not self._chunks.empty():
            try:
                self._chunks.get_nowait()
            except queue.Empty:
                break

        gap = time.time() - self._down_since if self._down_since else 0.0
        self._connected.set()
        self.log(f"satellite: streaming to {self.url}")
        if gap >= self.reconnect_notice_secs and self.on_reconnect:
            try:
                self.on_reconnect(gap)
            except Exception as e:
                self.log(f"satellite: reconnect notice failed ({e})")
        self._down_since = None

        sender = threading.Thread(target=self._send_loop, args=(conn,),
                                  name="satellite-uplink", daemon=True)
        sender.start()
        try:
            resp = conn.getresponse()
            if resp.status != 200:
                raise ConnectionError(f"sidecar returned {resp.status}")
            for raw in resp:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                self._event(event)
            raise ConnectionError("sidecar closed the stream")
        finally:
            self._connected.clear()
            try:
                conn.close()
            except Exception:
                pass

    def _send_loop(self, conn):
        try:
            while self._connected.is_set() and not self._stop.is_set():
                try:
                    chunk = self._chunks.get(timeout=1.0)
                except queue.Empty:
                    continue
                conn.send(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
        except Exception:
            # The reader raises and drives the reconnect; nothing to do here.
            self._connected.clear()

    def _event(self, event):
        kind = event.get("type")
        if kind == "wake":
            self._last_wake = event.get("text") or True
            self._wake.set()
            self.log(f"satellite: TRIGGER {event.get('text')!r} at {event.get('at')}s")
        elif kind == "ready":
            self.log("satellite: sidecar ready")


def wake_url(base):
    """WAKE_SIDECAR_URL may name the host or the full endpoint."""
    base = base.rstrip("/")
    return base if base.endswith("/listen") else f"{base}/listen"
