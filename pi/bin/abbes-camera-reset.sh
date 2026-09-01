#!/usr/bin/env bash
# Unwedge the webcam.
#
# This camera drops into EPROTO on every control transfer if anything ever asks
# it for a frame rate or for YUYV. Once there, it stays there: v4l2-ctl returns
# "VIDIOC_STREAMON: Input/output error" and every grab yields a zero-length file.
#
# A USB-level reset is enough on its own. Reloading uvcvideo is not, and cannot
# be done while the loop is running anyway -- "modprobe: FATAL: Module uvcvideo
# is in use" -- because the camera poller holds the device open. The reset is
# also the gentler of the two: it leaves the microphone, which is a function of
# this same USB device, to re-enumerate on its own.
#
# The loop notices on its own and logs "camera: recovered". Nothing needs
# restarting.
set -euo pipefail

dev=$(lsusb | awk '/webcam/{printf "/dev/bus/usb/%s/%s", $2, substr($4,1,3)}')
if [ -z "$dev" ]; then
    echo "no webcam on the USB bus" >&2
    exit 1
fi

echo "resetting $dev"
sudo python3 - "$dev" <<'EOF'
import fcntl, sys
USBDEVFS_RESET = ord("U") << 8 | 20
fcntl.ioctl(open(sys.argv[1], "wb"), USBDEVFS_RESET, 0)
EOF

# The device node can come back with a different minor number, so wait for it
# rather than assuming video0 is still there.
for _ in $(seq 15); do
    sleep 1
    [ -e /dev/video0 ] || continue
    if v4l2-ctl -d /dev/video0 --set-fmt-video=width=640,height=480,pixelformat=MJPG \
         --stream-mmap --stream-count=1 --stream-to=/tmp/.camtest.jpg >/dev/null 2>&1 &&
       [ -s /tmp/.camtest.jpg ]; then
        echo "camera back: $(stat -c%s /tmp/.camtest.jpg) byte frame"
        rm -f /tmp/.camtest.jpg
        exit 0
    fi
done

rm -f /tmp/.camtest.jpg
echo "still wedged; unplug it and plug it back in" >&2
exit 1
