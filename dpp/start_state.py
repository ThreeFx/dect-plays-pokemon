"""Create the state the event starts from: a new game, played up to the starter choice in Oak's lab.

    python -m dpp.start_state [--name RED] [--rival GREEN] [--out data/start.state.z]

The inputs are scripted and the emulator is deterministic, so the same names
always produce the same state. Start the game from it with

    python -m dpp --state data/start.state.z
"""

from __future__ import annotations

import argparse
import zlib
from pathlib import Path

from .emulator import Emulator
from .firered import read_player_name, read_position, read_stats
from .input import Button

# The naming screen's upper-case page; the cursor starts on A and moves over every cell, blanks included.
_KEYBOARD = ("ABCDEF .", "GHIJKL ,", "MNOPQRS ", "TUVWXYZ ")
_MAX_NAME = 7

# (map group, map number)
_BEDROOM = (4, 1)
_HOUSE = (4, 0)
_PALLET_TOWN = (3, 0)
_OAKS_LAB = (4, 3)


class _Player:
    """Presses buttons the way the scripted walkthrough needs them."""

    def __init__(self, emu: Emulator):
        self.emu = emu

    def wait(self, seconds: float) -> None:
        for _ in range(round(seconds * 60)):
            self.emu.run_frame()

    def tap(self, button: Button, times: int = 1) -> None:
        """Short presses, for menus and dialogue."""
        for _ in range(times):
            for _ in range(6):
                self.emu.run_frame(button)
            for _ in range(18):
                self.emu.run_frame()

    def walk(self, direction: Button, *, x: int | None = None, y: int | None = None, map: tuple[int, int] | None = None) -> None:
        """Walk in one direction until the player reaches the given coordinate or map."""
        for _ in range(30):
            group, number, px, py = read_position(self.emu)
            if (x is None or px == x) and (y is None or py == y) and (map is None or (group, number) == map):
                return
            for _ in range(16):  # one tile
                self.emu.run_frame(direction)
            for _ in range(8):
                self.emu.run_frame()
        raise RuntimeError(f"walking {direction.name} got stuck at {read_position(self.emu)}")

    def mash_until(self, button: Button, done, limit: int = 300) -> None:
        for _ in range(limit):
            if done():
                return
            self.tap(button)
        raise RuntimeError(f"mashing {button.name} never got there; position {read_position(self.emu)}")

    def type_name(self, name: str) -> None:
        """Enter a name on the naming screen and confirm it."""
        row = column = 0
        for letter in name:
            target_row = next(r for r, keys in enumerate(_KEYBOARD) if letter in keys)
            target_column = _KEYBOARD[target_row].index(letter)
            self.tap(Button.DOWN if target_row > row else Button.UP, abs(target_row - row))
            self.tap(Button.RIGHT if target_column > column else Button.LEFT, abs(target_column - column))
            self.tap(Button.A)
            row, column = target_row, target_column
        self.tap(Button.START)  # jumps to OK
        self.tap(Button.A)
        self.wait(5)  # back to the professor, who asks whether the name is right
        self.tap(Button.A)  # YES
        self.wait(3)


def create(rom: str | Path, name: str, rival: str) -> bytes:
    """Play a new game up to the starter choice and return the emulator state."""
    emu = Emulator(rom)
    player = _Player(emu)
    location = lambda: (read_position(emu) or (None,) * 4)[:2]  # noqa: E731

    # Title screen, the controls explanation and Oak's speech up to "Are you a boy?".
    player.wait(40)
    player.tap(Button.START)
    player.wait(3)
    player.tap(Button.A, 6)
    player.wait(2)
    player.tap(Button.A, 70)
    player.wait(4)
    player.tap(Button.A)  # BOY
    player.wait(2)
    player.tap(Button.A)
    player.wait(3)
    player.tap(Button.A)  # "What is your name?" opens the naming screen
    player.wait(3)
    player.type_name(name)

    # B advances the talk about the rival but, unlike A, does nothing in the name menu it ends on.
    player.tap(Button.B, 30)
    player.wait(2)
    player.tap(Button.A)  # NEW NAME
    player.wait(3)
    player.type_name(rival)
    player.mash_until(Button.B, lambda: location() == _BEDROOM)
    player.tap(Button.B, 10)
    player.wait(3)

    # Bedroom -> stairs -> front door -> north edge of Pallet Town, where Oak picks the player up.
    player.walk(Button.RIGHT, x=10)
    player.walk(Button.UP, y=2)
    player.walk(Button.LEFT, map=_HOUSE)
    player.wait(2)
    player.walk(Button.DOWN, y=3)
    player.walk(Button.LEFT, x=4)
    player.walk(Button.DOWN, map=_PALLET_TOWN)
    player.wait(2)
    player.walk(Button.RIGHT, x=12)
    player.walk(Button.UP, y=1)
    player.mash_until(Button.B, lambda: location() == _OAKS_LAB)
    player.tap(Button.B, 150)  # Oak's speech in the lab; B does nothing once it is over

    if read_player_name(emu) != name or read_stats(emu).party:
        raise RuntimeError(f"unexpected game state: player {read_player_name(emu)!r}, party {read_stats(emu).party}")
    state = emu.save_state()
    # The player must be free to move, otherwise the speech is still running.
    before = read_position(emu)
    player.walk(Button.DOWN, y=before[3] + 1)
    emu.load_state(state)
    return state


def _name(text: str) -> str:
    if not 1 <= len(text) <= _MAX_NAME or not all("A" <= letter <= "Z" for letter in text):
        raise argparse.ArgumentTypeError(f"names are 1 to {_MAX_NAME} letters A-Z")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("rom", nargs="?", default="pokemon-firered.gba")
    parser.add_argument("--name", type=_name, default="RED", help="the player's name")
    parser.add_argument("--rival", type=_name, default="GREEN", help="the rival's name")
    parser.add_argument("--out", type=Path, default=Path("data/start.state.z"))
    args = parser.parse_args()

    state = create(args.rom, args.name, args.rival)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(zlib.compress(state))
    print(f"wrote {args.out}: {args.name} in Oak's lab, about to choose a starter")


if __name__ == "__main__":
    main()
