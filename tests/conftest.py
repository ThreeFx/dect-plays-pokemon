import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def rom():
    """Path of the ROM; tests needing it are skipped when the bindings or the ROM are missing."""
    pytest.importorskip("mgba")
    path = Path(os.environ.get("DPP_ROM", ROOT / "pokemon-firered.gba"))
    if not path.exists():
        pytest.skip(f"no ROM at {path} (set DPP_ROM)")
    return path


@pytest.fixture
def emu(rom):
    """A freshly booted emulator."""
    from dpp.emulator import Emulator

    return Emulator(rom)
