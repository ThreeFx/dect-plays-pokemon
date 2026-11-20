#!/usr/bin/env bash
# Builds an SD card image for a Raspberry Pi (4 or 5, 64-bit) that boots
# straight into the game client: Raspberry Pi OS Lite with this repository,
# mGBA and the ROM installed.
#
# Needs Docker, and ARM emulation registered with the kernel (on Debian or
# Ubuntu: the qemu-user-static package). Takes a while: everything inside the
# image is compiled under emulation.
set -euo pipefail

# The Raspberry Pi OS release the image is built from.
BASE_URL=https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-2026-10-06/2026-10-06-raspios-trixie-arm64-lite.img.xz
BASE_SHA256=483db18a48da399b5b7022ffae9a07bc6d99daab30e593aedac09b69ff422843

root=$(cd "$(dirname "$0")/.." && pwd)
rom=$root/pokemon-firered.gba
state=$root/data/start.state.z
out=$root/dpp-client.img
server=
phone_number=7653
name=dpp-client
ssh_key=

usage() {
    cat <<USAGE
Usage: $0 [options]
  --rom FILE           the game ROM                     (default: pokemon-firered.gba)
  --state FILE         state a new game starts from     (default: data/start.state.z, if it exists)
  --server URL         server to sync with              (default: none, the client plays offline)
  --phone-number N     number shown on screen           (default: $phone_number)
  --name NAME          host name and client name        (default: $name)
  --ssh-key FILE       public key that may log in as root over SSH (default: SSH stays off)
  --out FILE           image to write                   (default: dpp-client.img)

Server, phone number and name can be changed later in dpp.env on the card's boot partition.
USAGE
}

while [ $# -gt 0 ]; do
    case $1 in
        --rom) rom=$2 ;;
        --state) state=$2 ;;
        --server) server=$2 ;;
        --phone-number) phone_number=$2 ;;
        --name) name=$2 ;;
        --ssh-key) ssh_key=$2 ;;
        --out) out=$2 ;;
        -h | --help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
    shift 2
done

fail() { echo "$*" >&2; exit 1; }
[ -f "$rom" ] || fail "No ROM at $rom (see --rom)."
[ -z "$ssh_key" ] || [ -f "$ssh_key" ] || fail "No SSH public key at $ssh_key."
[[ $name =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] || fail "--name must be a host name: lower-case letters, digits and hyphens."
[[ $phone_number =~ ^[0-9]+$ ]] || fail "--phone-number must be digits."
[[ ! $server =~ [[:space:]\'\"] ]] || fail "--server must be a plain URL."
command -v docker >/dev/null || fail "Docker is required."
[ -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ] || fail "ARM emulation is not set up; install qemu-user-static."

# Everything the image build reads goes into one directory that the container sees.
work=$(mktemp -d)
writing=
cleanup() {
    status=$?
    rm -rf "$work"
    # Do not leave a half-built image behind that looks like a finished one.
    if [ $status -ne 0 ] && [ -n "$writing" ]; then rm -f "$out"; fi
}
trap cleanup EXIT

cache=$root/vendor/pi
mkdir -p "$cache"
base=$cache/$(basename "$BASE_URL")
if ! echo "$BASE_SHA256  $base" | sha256sum --check --status 2>/dev/null; then
    echo "Downloading $(basename "$BASE_URL")"
    curl --fail --location --progress-bar --output "$base" "$BASE_URL"
    echo "$BASE_SHA256  $base" | sha256sum --check --status || fail "The downloaded image does not match its checksum."
fi

echo "Unpacking the base image to $out"
writing=1
xz --decompress --stdout "$base" > "$out"

# The repository as it is now: tracked files plus new ones that are not ignored.
git -C "$root" ls-files -z --cached --others --exclude-standard | tar -C "$root" --null --files-from=- -cf "$work/source.tar"
cp "$rom" "$work/rom.gba"
[ -f "$state" ] && cp "$state" "$work/start.state.z"
[ -n "$ssh_key" ] && cp "$ssh_key" "$work/authorized_keys"
cat > "$work/dpp.env" <<ENV
# Settings of the DECT plays Pokémon client; read at every start.
# The server to sync with, e.g. https://dpp.example.org; empty to play offline.
DPP_SERVER=$server
# Minutes between uploads to the server.
DPP_UPLOAD_INTERVAL=10
# The hotline's number shown on screen.
DPP_PHONE_NUMBER=$phone_number
# What the server's admin page calls this client.
DPP_NAME=$name
ENV
echo "$name" > "$work/hostname"

# Loop devices need a privileged container that sees the host's /dev.
docker run --rm --privileged \
    --volume /dev:/dev \
    --volume "$out":/image.img \
    --volume "$work":/work:ro \
    --volume "$cache":/cache \
    --volume "$root/pi":/pi:ro \
    debian:trixie-slim bash /pi/build-image.sh

echo
echo "The client ran inside the image; its screenshot is $cache/smoke-test.png"
echo "Wrote $out ($(du -h --apparent-size "$out" | cut -f1)). Flash it with Raspberry Pi Imager (\"Use custom\") or:"
echo "  sudo dd if=$out of=/dev/sdX bs=4M conv=fsync status=progress"
