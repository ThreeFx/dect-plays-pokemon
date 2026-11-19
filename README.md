# DECT plays Pokémon

Pokémon FireRed on a beamer, played by calling a phone number. See
[requirements.md](requirements.md) for the plan. This repository contains the
client (emulator and window) and the server that keeps its snapshots; the
phone side does not exist yet.

## Setup

Needs `git`, `cmake`, a C compiler, the Python headers (`python3-dev`) and
[uv](https://docs.astral.sh/uv/).

```sh
uv sync                    # Python dependencies into .venv
./scripts/build_mgba.sh    # mGBA 0.10.5 + its Python bindings into vendor/
```

Put the ROM (US FireRed 1.0 or 1.1, game code `BPRE`) at `pokemon-firered.gba`. ROMs
and everything under `data/` are git-ignored.

## Run

```sh
uv run python -m dpp                  # 1280x720 window
uv run python -m dpp --fullscreen     # beamer
uv run python -m dpp --state FILE     # start from a state file
uv run --extra server pytest
```

| Key | Action |
|---|---|
| `1`–`9` | the phone keys (stand-in until the phone part exists) |
| `Esc` | quit |

The client keeps nothing but the game's own cartridge save
(`data/firered.sav`) on disk. Progress is kept by the [server](#server); a
state downloaded from its page can be loaded with `--state`.

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

## Server

The server keeps the game safe off the client machine: it stores snapshots
and the button presses between them in an SQLite database, and decides what a
starting client continues from.

```sh
uv sync --extra server
DPP_PASSWORD=... uv run python -m dpp.server                  # http://127.0.0.1:8000
uv run python -m dpp --server http://127.0.0.1:8000 --state data/start.state.z
```

1. The client registers and shows `WAITING FOR ADMIN` with a 4-digit code.
2. On the server's web page (any user name, the password from `DPP_PASSWORD`)
   the client appears with the same code. Choose what it continues from, by
   default the most recent snapshot, and accept it.
3. The client loads that state and plays. Every 10 minutes
   (`--upload-interval`, in minutes) and when it quits, it uploads a snapshot
   with metadata and the button presses since the previous upload. If the
   server is unreachable the uploads wait and are retried.

When uploads are in trouble, a small dot appears in the top right corner of
the phone number panel: yellow while the server cannot be reached (the client
keeps retrying and catches up), red when the server refused an upload, for
example because another client was accepted. The reason is printed on the
client's console. The game itself is not interrupted.

The page shows each snapshot's party as the game's own icons, which the
server reads from the ROM (`--rom`, by default `pokemon-firered.gba` in the
directory it is started from). Without a ROM it lists names and levels.

A client has to be accepted every time it starts. Only one client is accepted
at a time; accepting another one stops the previous one from uploading. With
an empty database the client starts from `--state` or from power-on.

The page is also how you roll back: restart the client and pick an older
snapshot when accepting it.

The server listens on localhost unless told otherwise (`--host 0.0.0.0`). The
password travels as HTTP Basic auth, so across a network put the server behind
a reverse proxy that does TLS and give the client the `https://` URL.

## Code

| File | What it does |
|---|---|
| `dpp/emulator.py` | One GBA: step a frame with a key mask, read memory, save and load state |
| `dpp/input.py` | Buttons, the phone-key bindings, and the press queue the phone part will feed |
| `dpp/firered.py` | Reads badges and party out of the game's RAM, and badge and Pokémon icons out of the ROM |
| `dpp/gui.py` | The window: game screen, phone number, key bindings, party, badges |
| `dpp/start_state.py` | Generates the state the event starts from |
| `dpp/sync.py` | Client side of the server protocol: approval, input log, uploads |
| `dpp/server/` | The server: client API, admin page, database |
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
