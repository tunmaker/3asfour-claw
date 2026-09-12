#!/usr/bin/env bash
# Recover USB audio after the controller's isochronous scheduling wedges.
#
# The symptom is specific and does not look like a broken microphone: every
# capture returns a 44-byte WAV -- a RIFF header and no samples -- while ALSA
# reports the stream "Running", PipeWire lists the source "RUNNING", and the
# device is still enumerated. Both microphones on the machine go at once, and
# Ethernet on the same hub keeps working. The kernel says what happened:
#
#   Transfer to device N endpoint 0xN failed - FIQ reported NYET.
#
# A USB reset of the device does NOT fix this, with or without something holding
# the device open -- both were measured. The wedge is not in the device: a FIQ
# channel is stuck holding the hub's transaction-translator reservation, and
# re-enumerating the device never touches host controller state. Rebinding the
# controller does.
#
# THIS DROPS EVERY USB DEVICE FOR A FEW SECONDS, INCLUDING ETHERNET, because on
# a Pi every port is behind one hub on this controller. Over SSH you will lose
# the connection. That is why the rebind is detached and followed by a watchdog:
# if the network does not come back, the Pi reboots itself rather than sitting
# unreachable.
set -uo pipefail

HCD=$(ls /sys/bus/platform/drivers/dwc_otg/ 2>/dev/null | grep -m1 '\.usb$')
[ -n "$HCD" ] || { echo "no dwc_otg controller found" >&2; exit 1; }

GATEWAY=$(ip route | awk '/^default/{print $3; exit}')

echo "rebinding $HCD (all USB drops for a few seconds)"
setsid sudo sh -c "
    echo $HCD > /sys/bus/platform/drivers/dwc_otg/unbind
    sleep 3
    echo $HCD > /sys/bus/platform/drivers/dwc_otg/bind
    # The network is the way back in. If it does not return, nothing else here
    # can be checked anyway, so take the reboot rather than the silence.
    for _ in \$(seq 60); do
        sleep 1
        ping -c1 -W1 ${GATEWAY:-127.0.0.1} >/dev/null 2>&1 && exit 0
    done
    logger -t abbes-unwedge 'network did not return after USB rebind; rebooting'
    reboot
" >/dev/null 2>&1 < /dev/null &

echo "rebind running detached; the connection may drop. Reconnect and verify with:"
echo "  arecord -l && parecord --device=\$MIC_SOURCE -d 3 /tmp/t.wav && stat -c%s /tmp/t.wav"
echo "44 bytes means still wedged: reboot is the remaining cure."
