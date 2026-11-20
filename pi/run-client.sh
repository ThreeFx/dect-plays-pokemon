#!/bin/sh
# The X session of the kiosk: starts the client full screen. Started by startx
# from the dpp user's login on tty1 (see provision.sh).
set -a
[ -f /boot/firmware/dpp.env ] && . /boot/firmware/dpp.env
set +a

# Keep the picture on: no screen saver, no display power management.
xset s off -dpms

set -- --fullscreen --data /var/lib/dpp --phone-number "${DPP_PHONE_NUMBER:-7653}"
if [ -n "${DPP_SERVER:-}" ]; then
    set -- "$@" --server "$DPP_SERVER" --upload-interval "${DPP_UPLOAD_INTERVAL:-10}" --name "${DPP_NAME:-$(hostname)}"
fi
if [ -f /var/lib/dpp/start.state.z ]; then
    set -- "$@" --state /var/lib/dpp/start.state.z
fi

cd /opt/dpp
PYTHONUNBUFFERED=1 exec .venv/bin/python -m dpp "$@"
