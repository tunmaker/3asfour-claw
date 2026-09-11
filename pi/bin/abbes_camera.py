"""Frames from the USB webcam, on a slow poll, to the orchestrator.

This is deliberately not a video stream. Measured on this camera:

    20 single-shot MJPG grabs at ~1/s ... 19 succeeded, mic unaffected
    continuous stream, 75 frames @5fps .. VIDIOC_STREAMON: Input/output error

Any attempt to set a frame rate, or to select YUYV, wedges the device into
EPROTO on every subsequent control transfer, and recovery needs a USB-level
reset *and* a uvcvideo reload. So there is exactly one invocation here, it never
touches the format beyond MJPG at the default rate, and a failed grab is
routine rather than an error.

This file used to be careful for a second reason: the camera and the microphone
were two functions of one USB device, so polling competed with hearing and a
wedge took the microphone with it -- parecord stayed alive delivering nothing,
the wake word never fired, and the assistant was silently deaf for ninety
minutes until the bus was reset by hand.

The microphone is now in the speakerphone, a different device entirely, so a
wedged camera is a lost camera and nothing more. The poller no longer resets the
bus on its own: doing so would drop a *working* microphone to recover a camera.
It backs off instead, and a wedge that does not clear is repaired by hand with
`abbes-camera-reset.sh`. The `repair` hook is left here for a host where the two
do share a device again.

Stdlib only, like the rest of the Pi.
"""
import pathlib
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

# The one invocation that works. Do not add --set-parm.
GRAB = [
    "v4l2-ctl", "-d", "{device}",
    "--set-fmt-video=width={width},height={height},pixelformat=MJPG",
    "--stream-mmap", "--stream-count=1", "--stream-to={path}",
]


class Camera:
    def __init__(self, device="/dev/video0", width=640, height=480, log=lambda *a: None):
        self.device = device
        self.width = width
        self.height = height
        self.log = log
        self.path = pathlib.Path(tempfile.gettempdir()) / "abbes-frame.jpg"

    def grab(self):
        """One JPEG, or None. None is expected roughly one time in twenty."""
        cmd = [p.format(device=self.device, width=self.width, height=self.height, path=self.path)
               for p in GRAB]
        try:
            subprocess.run(cmd, capture_output=True, timeout=10)
        except (subprocess.TimeoutExpired, OSError) as e:
            self.log(f"camera: grab failed ({e})")
            return None
        try:
            data = self.path.read_bytes()
        except OSError:
            return None
        finally:
            self.path.unlink(missing_ok=True)
        # A wedged device leaves a zero-length file rather than failing outright.
        return data if len(data) > 1024 else None


class CameraPoller:
    """Polls on an interval and posts each frame. Never raises into the loop."""

    def __init__(self, url, camera, interval=3.0, log=lambda *a: None,
                 timeout=30, wedge_after=10, wedge_interval=300.0,
                 repair=None, idle=None):
        self.url = url
        self.camera = camera
        self.interval = interval
        self.log = log
        self.timeout = timeout
        self.wedge_after = wedge_after
        self.wedge_interval = wedge_interval
        self.repair = repair
        # The reset drops the USB device for a moment, so it waits for a turn to
        # finish rather than cutting the microphone out from under one.
        self.idle = idle or (lambda: True)
        self.repairs = 0
        self._stop = threading.Event()
        self._thread = None
        self.consecutive_failures = 0
        self.sent = 0
        self.changes = 0

    def start(self):
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        self._stop.set()

    def _run(self):
        self.log(f"camera: polling {self.camera.device} every {self.interval:g}s -> {self.url}")
        while not self._stop.is_set():
            started = time.monotonic()
            frame = self.camera.grab()
            if frame is None:
                self.consecutive_failures += 1
                if self.consecutive_failures == self.wedge_after:
                    self.log(f"camera: {self.wedge_after} grabs failed in a row; the "
                             f"device is wedged. Backing off to {self.wedge_interval:g}s "
                             f"until it comes back.")
                if self.wedged:
                    self._try_repair()
            else:
                if self.wedged:
                    self.log("camera: recovered")
                self.consecutive_failures = 0
                self._post(frame)
            interval = self.wedge_interval if self.wedged else self.interval
            self._stop.wait(max(0.0, interval - (time.monotonic() - started)))

    @property
    def wedged(self):
        return self.consecutive_failures >= self.wedge_after

    def _try_repair(self):
        """Reset the bus, once the loop is between turns."""
        if not self.repair or not self.idle():
            return
        self.repairs += 1
        self.log(f"camera: resetting the USB device (attempt {self.repairs})")
        try:
            ok = self.repair()
        except Exception as e:
            self.log(f"camera: reset failed ({e})")
            return
        self.log("camera: reset done" if ok else "camera: reset did not take")

    def _post(self, frame):
        req = urllib.request.Request(self.url, data=frame,
                                     headers={"Content-Type": "image/jpeg"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                self.sent += 1
                body = resp.read(400).decode("utf-8", "replace")
                if '"changed":true' in body.replace(" ", ""):
                    self.changes += 1
                    self.log(f"camera: scene change reported ({body[:160]})")
        except urllib.error.HTTPError as e:
            self.log(f"camera: orchestrator returned {e.code}")
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            # The orchestrator being down must not stop the poll; it comes back.
            self.log(f"camera: post failed ({e})")


def frame_url(orchestrator_url):
    """Derive the frame endpoint from the configured turn endpoint."""
    base = orchestrator_url.split("/turn")[0].rstrip("/")
    return f"{base}/vision/frame"
