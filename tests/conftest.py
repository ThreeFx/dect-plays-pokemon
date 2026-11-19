import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def emu():
    """A freshly booted emulator; skipped when the bindings or the ROM are missing."""
    pytest.importorskip("mgba")
    rom = Path(os.environ.get("DPP_ROM", ROOT / "pokemon-firered.gba"))
    if not rom.exists():
        pytest.skip(f"no ROM at {rom} (set DPP_ROM)")
    from dpp.emulator import Emulator

    return Emulator(rom)
