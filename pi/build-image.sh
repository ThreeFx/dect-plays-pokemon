#!/usr/bin/env bash
# Runs as root inside the build container (see scripts/make_pi_image.sh):
# makes room in /image.img, mounts it and runs provision.sh inside it.
set -euo pipefail

EXTRA_SPACE=3G  # for compilers, X and the mGBA build; the Pi grows the card to full size on first boot anyway

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends parted e2fsprogs dosfstools >/dev/null

truncate --size +$EXTRA_SPACE /image.img
parted --script /image.img resizepart 2 100%

target=/mnt/target
loop=$(losetup --find --show --partscan /image.img)
cleanup() {
    umount --recursive "$target" 2>/dev/null || true
    losetup --detach "$loop"
}
trap cleanup EXIT
for _ in $(seq 50); do [ -b "${loop}p2" ] && break; sleep 0.1; done

e2fsck -f -p "${loop}p2" >/dev/null || [ $? -le 1 ]  # 1 means "errors corrected"
resize2fs "${loop}p2" >/dev/null

mkdir -p "$target"
mount "${loop}p2" "$target"
mount "${loop}p1" "$target/boot/firmware"

# What programs inside the image need to run here. /dev is a minimal private
# one, so nothing in the image can touch the build machine's devices.
mount -t proc proc "$target/proc"
mount -t sysfs -o ro sysfs "$target/sys"
mount -t tmpfs -o mode=755 tmpfs "$target/dev"
mknod -m 666 "$target/dev/null" c 1 3
mknod -m 666 "$target/dev/zero" c 1 5
mknod -m 666 "$target/dev/full" c 1 7
mknod -m 666 "$target/dev/random" c 1 8
mknod -m 666 "$target/dev/urandom" c 1 9
mknod -m 666 "$target/dev/tty" c 5 0
ln -s /proc/self/fd "$target/dev/fd"
mkdir "$target/dev/pts" "$target/dev/shm"
mount -t devpts -o newinstance,ptmxmode=666 devpts "$target/dev/pts"
ln -s pts/ptmx "$target/dev/ptmx"
mount -t tmpfs tmpfs "$target/dev/shm"
mount -t tmpfs tmpfs "$target/tmp"
mount -t tmpfs tmpfs "$target/run"
mount --bind /etc/resolv.conf "$target/etc/resolv.conf"  # name resolution, without changing the image's file

mkdir -p "$target/opt/dpp" "$target/tmp/work"
tar -xf /work/source.tar -C "$target/opt/dpp"
cp /work/* "$target/tmp/work/"

chroot "$target" /bin/bash /opt/dpp/pi/provision.sh

install -m 644 /work/dpp.env "$target/boot/firmware/dpp.env"
cp "$target/tmp/work/smoke-test.png" /cache/smoke-test.png
chown --reference=/cache /cache/smoke-test.png  # not root's, like the rest of that directory
echo "Free space left in the image: $(df -h --output=avail "$target" | tail -1 | tr -d ' ')"
