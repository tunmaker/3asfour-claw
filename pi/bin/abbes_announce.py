"""Speech the Pi did not ask for.

Every turn until now started here: the Pi heard its name, recorded, posted, and
played the answer. Nothing could reach the speaker unless the Pi had asked for
it. Prayer times and calendar events do not wait to be asked, so this opens one
long-lived GET to the orchestrator and plays whatever comes down it.

The connection carries nothing while there is nothing to say, so an idle
household costs one socket and no traffic. The orchestrator decides *whether*
to speak -- quiet hours, and never over a live turn -- because it is the only
side that can see every reason not to. This end only decides how.

Stdlib only, like the rest of the Pi.
"""
import json
import struct
import threading
import time
import urllib.error
import urllib.request

FRAME_SPEECH = 0x81
FRAME_SPEECH_END = 0x82
FRAME_CONTROL = 0x83

# Long enough that a quiet night does not reconnect, short enough that a dead
# socket is noticed. The orchestrator sends nothing between announcements, so
# this is the only thing that distinguishes silence from a broken link.
READ_TIMEOUT = 900


def _read_exactly(fh, n):
    buf = b""
    while len(buf) < n:
        c = fh.read(n - len(buf))
        if not c:
            return None
        buf += c
    return buf


class AnnounceListener:
    """Holds the downlink open and plays what arrives.

    `make_player` is called per announcement rather than once, so a dead
    playback process cannot poison every future announcement -- the same reason
    a turn builds its own.
    """

    def __init__(self, url, make_player, mute_ctx, log=lambda *a: None,
                 on_reconnect=None, reconnect_notice_secs=120):
        self.url = url
        self.make_player = make_player
        self.mute_ctx = mute_ctx
        self.log = log
        self.on_reconnect = on_reconnect
        self.reconnect_notice_secs = reconnect_notice_secs
        self._stop = threading.Event()
        self._thread = None
        self._connected_at = None
        self._down_since = None
        self._player = None
        self._mute = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="announce", daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        self._stop.set()

    @property
    def connected(self):
        return self._connected_at is not None

    def _run(self):
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._session()
                backoff = 1.0
            except Exception as e:
                if self._down_since is None:
                    self._down_since = time.time()
                self.log(f"announce: link down ({e}); retrying in {backoff:.0f}s")
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 60.0)

    def _session(self):
        req = urllib.request.Request(self.url, headers={"Accept": "application/octet-stream"})
        resp = urllib.request.urlopen(req, timeout=READ_TIMEOUT)
        self._connected_at = time.time()
        gap = time.time() - self._down_since if self._down_since else 0.0
        self.log(f"announce: listening on {self.url}")

        # Silent deafness is the failure mode worth spending a sentence on: from
        # the room, an assistant that cannot hear looks exactly like one that is
        # ignoring you. Only after a gap long enough to have been noticed.
        if gap >= self.reconnect_notice_secs and self.on_reconnect:
            try:
                self.on_reconnect(gap)
            except Exception as e:
                self.log(f"announce: reconnect notice failed ({e})")
        self._down_since = None

        try:
            while not self._stop.is_set():
                head = _read_exactly(resp, 5)
                if head is None:
                    raise ConnectionError("orchestrator closed the stream")
                kind = head[0]
                (length,) = struct.unpack(">I", head[1:5])
                body = _read_exactly(resp, length)
                if body is None:
                    raise ConnectionError("truncated frame")
                self._frame(kind, body)
        finally:
            self._connected_at = None
            if self._down_since is None:
                self._down_since = time.time()
            try:
                resp.close()
            except Exception:
                pass

    def _frame(self, kind, body):
        if kind == FRAME_CONTROL:
            self.log(f"announce: control {body.decode('utf-8', 'replace')[:120]}")
            return
        if kind == FRAME_SPEECH:
            self._speak_chunk(body)
            return
        if kind == FRAME_SPEECH_END:
            self._finish()
            return
        self.log(f"announce: unknown frame kind {kind:#x}, {len(body)} bytes")

    def _speak_chunk(self, wav):
        if self._player is None:
            self._enter_playback()
        self._player.write_wav(wav)

    def _enter_playback(self):
        self._mute = self.mute_ctx()
        self._mute.__enter__()
        self._player = self.make_player()

    def _finish(self):
        player, self._player = self._player, None
        mute, self._mute = self._mute, None
        try:
            if player:
                player.close()
        finally:
            if mute:
                # The mute tail lives in the context manager, so unmuting waits
                # for the speaker the same way a turn does.
                mute.__exit__(None, None, None)
        if player:
            self.log("announce: spoken")


def announce_url(orchestrator_url):
    """Derive the announce endpoint from the configured turn endpoint.

    One setting stays one setting: ORCHESTRATOR_URL already names the host and
    port, and deriving avoids a second URL that can drift out of step with it.
    """
    base = orchestrator_url.split("/turn")[0].rstrip("/")
    return f"{base}/announce/stream"
