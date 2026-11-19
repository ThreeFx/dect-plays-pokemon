"""One emulated GBA, stepped frame by frame through mGBA's Python bindings."""

from __future__ import annotations

import os
from pathlib import Path

import mgba.core
import mgba.image
import mgba.log
from mgba._pylib import ffi, lib

from .input import Button

# Flags for mCoreSaveStateNamed (include/mgba/core/serialize.h). Including the
# cartridge save keeps the in-game save consistent with the state on rollback.
_SAVESTATE_SAVEDATA = 2

# GBA memory regions that can be read as whole blocks: base address -> mGBA block id.
_BLOCKS = {0x02000000: 2, 0x03000000: 3, 0x08000000: 8}


class Emulator:
    WIDTH = 240
    HEIGHT = 160
    FPS = 16777216 / 280896  # GBA clock / cycles per frame, about 59.73

    def __init__(self, rom: str | Path, save: str | Path | None = None):
        mgba.log.silence()
        core = mgba.core.load_path(str(rom))
        if core is None:
            raise ValueError(f"mGBA cannot load {rom}")
        self._core = core
        self._native = core._core
        if ffi.sizeof("color_t") != 4:
            raise RuntimeError("mGBA was built with 16-bit colour; rebuild without COLOR_16_BIT")

        self._image = mgba.image.Image(*core.desired_video_dimensions())
        core.set_video_buffer(self._image)
        if save is not None:
            vf = lib.VFileOpen(str(save).encode(), os.O_RDWR | os.O_CREAT)
            if vf == ffi.NULL or not self._native.loadSave(self._native, vf):
                raise OSError(f"cannot open save file {save}")
        core.reset()
        # reset() reallocates work RAM, so the block pointers are only valid after it.
        self._blocks = {base: self._block(block_id) for base, block_id in _BLOCKS.items()}

    def _block(self, block_id: int):
        size = ffi.new("size_t*")
        pointer = self._native.getMemoryBlock(self._native, block_id, size)
        return ffi.buffer(pointer, size[0])

    @property
    def game_code(self) -> str:
        return self._core.game_code

    @property
    def frame(self) -> int:
        """Frames emulated since power-on. Savestates carry it, so loading one rewinds it."""
        return self._core.frame_counter

    def run_frame(self, keys: Button | int = 0) -> None:
        """Emulate one frame with exactly these buttons held."""
        self._core.set_keys(raw=int(keys))
        self._core.run_frame()

    @property
    def framebuffer(self):
        """The current screen as a live RGBX byte buffer of WIDTH x HEIGHT pixels (no copy)."""
        return ffi.buffer(self._image.buffer)

    def read(self, address: int, length: int) -> bytes:
        """Read memory from work RAM (0x02..., 0x03...) or the ROM (0x08...)."""
        base = address & 0xFF000000
        offset = address - base
        block = self._blocks.get(base)
        if block is None or offset + length > len(block):
            raise ValueError(f"cannot read {length} bytes at {address:#010x}")
        return block[offset : offset + length]

    def read_u8(self, address: int) -> int:
        return self.read(address, 1)[0]

    def read_u16(self, address: int) -> int:
        return int.from_bytes(self.read(address, 2), "little")

    def read_u32(self, address: int) -> int:
        return int.from_bytes(self.read(address, 4), "little")

    def save_state(self) -> bytes:
        """Snapshot the whole machine, including the cartridge save."""
        vf = lib.VFileMemChunk(ffi.NULL, 0)
        try:
            if not lib.mCoreSaveStateNamed(self._native, vf, _SAVESTATE_SAVEDATA):
                raise RuntimeError("mGBA failed to save state")
            size = vf.size(vf)
            data = ffi.new("char[]", size)
            vf.seek(vf, 0, os.SEEK_SET)
            vf.read(vf, data, size)
            return bytes(ffi.buffer(data, size))
        finally:
            vf.close(vf)

    def load_state(self, state: bytes) -> None:
        """Restore a snapshot made by save_state()."""
        vf = lib.VFileMemChunk(state, len(state))
        try:
            if not lib.mCoreLoadStateNamed(self._native, vf, _SAVESTATE_SAVEDATA):
                raise ValueError("mGBA rejected the state")
        finally:
            vf.close(vf)
