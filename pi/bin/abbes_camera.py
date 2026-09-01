"""Frames from the USB webcam, on a slow poll, to the orchestrator.

This is deliberately not a video stream. Measured on this camera:

    20 single-shot MJPG grabs at ~1/s ... 19 succeeded, mic unaffected
    continuous stream, 75 frames @5fps .. VIDIOC_STREAMON: Input/output error

Any attempt to set a frame rate, or to select YUYV, wedges the device into
EPROTO on every subsequent control transfer, and recovery needs a USB-level
reset *and* a uvcvideo reload. So there is exactly one invocation here, it never
touches the format beyond MJPG at the default rate, and a failed grab is
routine rather than an error.

The camera and the microphone are the same USB device. Polling was measured not
to disturb capture, but that is why the interval is seconds rather than
milliseconds, and why nothing here ever tries to reset the bus: the microphone
is the more important of the two functions, and it is not worth risking to
recover a frame.

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
                 timeout=30, wedge_after=10):
        self.url = url
        self.camera = camera
        self.interval = interval
        self.log = log
        self.timeout = timeout
        self.wedge_after = wedge_after
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
                # Do not try to fix this from here. A USB reset would take the
                # microphone down with it, and a deaf assistant is worse than a
                # blind one.
                if self.consecutive_failures == self.wedge_after:
                    self.log(f"camera: {self.wedge_after} grabs failed in a row; "
                             f"the device is probably wedged and needs "
                             f"'sudo modprobe -r uvcvideo && sudo modprobe uvcvideo' "
                             f"after a USB reset. Still listening.")
            else:
                if self.consecutive_failures >= self.wedge_after:
                    self.log("camera: recovered")
                self.consecutive_failures = 0
                self._post(frame)
            self._stop.wait(max(0.0, self.interval - (time.monotonic() - started)))

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
