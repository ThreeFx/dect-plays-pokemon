#!/usr/bin/env bash
# Runs as root inside the Raspberry Pi OS image, under ARM emulation (see
# build-image.sh): installs the client and makes the Pi boot straight into it.
set -euo pipefail

UV_VERSION=0.11.28
work=/tmp/work
export DEBIAN_FRONTEND=noninteractive

# This is not a running system: package installation must not start services.
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
chmod +x /usr/sbin/policy-rc.d
trap 'rm -f /usr/sbin/policy-rc.d' EXIT

echo "== Installing packages"
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    build-essential cmake git pkg-config python3-dev python3-venv libpng-dev zlib1g-dev \
    xserver-xorg-core xserver-xorg-input-libinput xinit x11-xserver-utils xauth xvfb \
    libgl1 libgl1-mesa-dri libegl1 libgles2 \
    libx11-6 libxext6 libxrandr2 libxcursor1 libxi6 libxinerama1 libxss1 libxxf86vm1 libxkbcommon0 \
    >/dev/null

echo "== Installing the client"
python3 -m venv /opt/uv
/opt/uv/bin/pip install --quiet "uv==$UV_VERSION"
cd /opt/dpp
# Use the system's Python, whose headers python3-dev provides, for the mGBA bindings.
UV_PYTHON_DOWNLOADS=never UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy /opt/uv/bin/uv sync --frozen --quiet
./scripts/build_mgba.sh > /tmp/mgba-build.log 2>&1 || { tail -40 /tmp/mgba-build.log; exit 1; }
tail -1 /tmp/mgba-build.log
install -m 644 "$work/rom.gba" /opt/dpp/pokemon-firered.gba
.venv/bin/python -m compileall -q dpp

echo "== Setting up the kiosk"
# The game runs as its own unprivileged user, logged in automatically on the
# first console; the login starts X with the client as its only program.
useradd --create-home --shell /bin/bash --groups video,render,input,audio dpp
install -d -o dpp -g dpp /var/lib/dpp
if [ -f "$work/start.state.z" ]; then
    install -o dpp -g dpp -m 644 "$work/start.state.z" /var/lib/dpp/start.state.z
fi
install -d /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/dpp-autologin.conf <<'UNIT'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin dpp --noclear %I $TERM
# When the client exits, the login ends and this brings it back.
RestartSec=3
UNIT
cat > /home/dpp/.bash_profile <<'PROFILE'
# Start the game on the console this user is logged in on automatically.
# Its output goes to the journal: journalctl -t dpp-client
if [ -z "${DISPLAY:-}" ] && [ "$(tty)" = /dev/tty1 ]; then
    trap '' INT
    exec systemd-cat --identifier=dpp-client startx /opt/dpp/pi/run-client.sh -- -nocursor
fi
PROFILE
chown dpp:dpp /home/dpp/.bash_profile
# The Pi has separate graphics devices for 3D and for the display; X must use the display one.
install -d /etc/X11/xorg.conf.d
cat > /etc/X11/xorg.conf.d/99-vc4.conf <<'XORG'
Section "OutputClass"
    Identifier "vc4"
    MatchDriver "vc4"
    Driver "modesetting"
    Option "PrimaryGPU" "true"
EndSection
XORG

# Raspberry Pi OS would otherwise ask for a user name on the first boot. Masked,
# not disabled: on its first boot systemd enables every service that is not.
systemctl mask --quiet userconfig.service
systemctl enable --quiet getty@tty1.service

hostname=$(cat "$work/hostname")
echo "$hostname" > /etc/hostname
sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$hostname/" /etc/hosts
# cloud-init runs on the first boot and must leave the host name alone.
echo "preserve_hostname: true" > /etc/cloud/cloud.cfg.d/99_dpp.cfg

if [ -f "$work/authorized_keys" ]; then
    echo "== Enabling SSH for root with the given key"
    install -d -m 700 /root/.ssh
    install -m 600 "$work/authorized_keys" /root/.ssh/authorized_keys
    rm -f /etc/ssh/sshd_config.d/rename_user.conf
    printf 'PasswordAuthentication no\nPermitRootLogin prohibit-password\n' > /etc/ssh/sshd_config.d/dpp.conf
    systemctl enable --quiet ssh.service
    echo "disable_root: false" >> /etc/cloud/cloud.cfg.d/99_dpp.cfg  # or cloud-init may block root's key
fi

echo "== Smoke test: the client in a virtual X display, as the kiosk user"
install -d -o dpp -g dpp /tmp/smoke
state_arg=()
[ -f /var/lib/dpp/start.state.z ] && state_arg=(--state /var/lib/dpp/start.state.z)
runuser -u dpp -- env SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
    xvfb-run --server-args="-screen 0 1920x1080x24" \
    .venv/bin/python -m dpp --fullscreen --data /tmp/smoke "${state_arg[@]}" --frames 120 --screenshot /tmp/smoke/smoke-test.png
test -s /tmp/smoke/smoke-test.png
cp /tmp/smoke/smoke-test.png "$work/smoke-test.png"

apt-get clean
rm -rf /var/lib/apt/lists/*
echo "== Done"
