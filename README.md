# DECT plays Pokémon

Pokémon FireRed on a beamer, played by calling a phone number. See
[requirements.md](requirements.md) for the plan. This repository currently
contains the emulator side; the phone side does not exist yet.

## Setup

Needs `git`, `cmake`, a C compiler, the Python headers (`python3-dev`) and
[uv](https://docs.astral.sh/uv/).

```sh
uv sync                    # Python dependencies into .venv
./scripts/build_mgba.sh    # mGBA 0.10.5 + its Python bindings into vendor/
```

Put the ROM (US FireRed 1.0 or 1.1, game code `BPRE`) at `pokemon-firered.gba`. ROMs,
saves and snapshots are git-ignored.

## Run

```sh
uv run python -m dpp                  # 1280x720 window
uv run python -m dpp --fullscreen     # beamer
uv run python -m dpp --resume         # continue from the latest snapshot
uv run python -m dpp --state FILE     # start from a specific snapshot or state file
uv run pytest
```

| Key | Action |
|---|---|
| `1`–`9` | the phone keys (stand-in until the phone part exists) |
| `F5` | save a snapshot |
| `F9` | roll back to the latest snapshot |
| `Esc` | save a snapshot and quit |

A snapshot is written every 60 s (`--snapshot-interval`) to `data/snapshots/`,
and once more on quit or `SIGTERM`.

## Skipping the intro

```sh
uv run python -m dpp.start_state --name RED --rival GREEN   # writes data/start.state.z
uv run python -m dpp --state data/start.state.z
```

`dpp.start_state` plays a new game with scripted inputs up to Oak's lab, where
the three starters wait on the table, and saves that state. Names are 1 to 7
letters A–Z. The same names always give the same state.

Loading any state also replaces the cartridge save (`data/firered.sav`) with
the one stored in the state.

## Code

| File | What it does |
|---|---|
| `dpp/emulator.py` | One GBA: step a frame with a key mask, read memory, save and load state |
| `dpp/input.py` | Buttons, the phone-key bindings, and the press queue the phone part will feed |
| `dpp/firered.py` | Reads badges and party out of the game's RAM, and the badge icons out of the ROM |
| `dpp/gui.py` | The window: game screen, phone number, key bindings, party, badges |
| `dpp/snapshots.py` | Snapshot files |
| `dpp/start_state.py` | Generates the state the event starts from |
| `patches/` | Changes applied to the mGBA source before building |

Sending input from Python:

```python
from dpp.input import Button, InputQueue

inputs = InputQueue()          # thread-safe
inputs.press_phone_key("5")    # or inputs.press(Button.A)
```

The emulator is deterministic: a snapshot plus the key mask of every frame
after it reproduces the same game state (`tests/test_emulator.py`).

The font is [Press Start 2P](https://fonts.google.com/specimen/Press+Start+2P),
SIL Open Font License (`dpp/assets/PressStart2P-OFL.txt`).
