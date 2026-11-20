#!/usr/bin/env bash
# Builds mGBA and its upstream Python bindings into vendor/ and makes the
# `mgba` package importable from .venv. Run `uv sync` first.
# To change the mGBA version, edit MGBA_REF and delete vendor/.
set -euo pipefail

MGBA_REF=0.10.5

root=$(cd "$(dirname "$0")/.." && pwd)
src=$root/vendor/mgba
build=$root/vendor/mgba-build
venv=$root/.venv

if [ ! -x "$venv/bin/python" ]; then
    echo "No virtualenv at $venv; run 'uv sync' first." >&2
    exit 1
fi

if [ ! -d "$src" ]; then
    git clone --depth 1 --branch "$MGBA_REF" https://github.com/mgba-emu/mgba.git "$src"
    for patch in "$root"/patches/mgba-*.patch; do
        git -C "$src" apply "$patch"
    done
fi

# mGBA's CMake files pick up the Python interpreter from the active virtualenv.
export VIRTUAL_ENV=$venv
export PATH=$venv/bin:$PATH

# The generated binding code declares va_list as a plain pointer. GCC 14 and
# later treat that mismatch as an error; it only affects a compile-time type
# check, so keep it a warning. Both CMake and the bindings' setup.py read CFLAGS.
export CFLAGS="${CFLAGS:-} -Wno-error=incompatible-pointer-types"

# Only the emulator core and the bindings; no frontends, no optional libraries.
cmake -S "$src" -B "$build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_PYTHON=ON -DBUILD_SHARED=ON -DBUILD_STATIC=OFF \
    -DBUILD_QT=OFF -DBUILD_SDL=OFF \
    -DBUILD_GL=OFF -DBUILD_GLES2=OFF -DBUILD_GLES3=OFF -DUSE_EPOXY=OFF \
    -DENABLE_SCRIPTING=OFF -DUSE_LUA=OFF \
    -DUSE_FFMPEG=OFF -DUSE_DISCORD_RPC=OFF -DUSE_SQLITE3=OFF \
    -DUSE_LIBZIP=OFF -DUSE_MINIZIP=OFF -DUSE_ELF=OFF \
    -DUSE_EDITLINE=OFF -DUSE_GDB_STUB=OFF
cmake --build "$build" --parallel

site_packages=$("$venv/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
printf '%s\n' "$build"/python/lib.* > "$site_packages/mgba.pth"

"$venv/bin/python" -c 'from mgba._pylib import ffi, lib; print("mGBA", ffi.string(lib.projectVersion).decode(), "Python bindings ready")'
