"""Stores emulator snapshots as compressed files in a directory."""

from __future__ import annotations

import time
import zlib
from pathlib import Path

from .emulator import Emulator


class SnapshotStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, emu: Emulator) -> Path:
        """Write the current state; file names sort by creation time and carry the frame number."""
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        path = self.directory / f"{stamp}-f{emu.frame:010d}.state.z"
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(zlib.compress(emu.save_state()))
        temporary.replace(path)  # a crash mid-write must not leave a half snapshot behind
        return path

    def latest(self) -> Path | None:
        return max(self.directory.glob("*.state.z"), default=None)

    @staticmethod
    def load(emu: Emulator, path: str | Path) -> None:
        emu.load_state(zlib.decompress(Path(path).read_bytes()))
