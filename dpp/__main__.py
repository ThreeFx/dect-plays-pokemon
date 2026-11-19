"""Run the game window: python -m dpp [ROM]"""

from __future__ import annotations

import argparse
import socket
import time
import urllib.error
import zlib
from pathlib import Path

import pygame

from .emulator import Emulator
from .firered import DEMO_STATS, read_badge_icons, read_mon_icon, read_stats
from .gui import Frame
from .input import InputQueue
from .sync import Server, Uplink

# Keyboard stand-ins for the phone keys, until the phone part exists.
_PHONE_KEYS = {getattr(pygame, f"K_{d}"): str(d) for d in range(1, 10)}
_PHONE_KEYS |= {getattr(pygame, f"K_KP{d}"): str(d) for d in range(1, 10)}

_POLL_SECONDS = 2
_FINAL_UPLOAD_SECONDS = 15


def _quit_requested(event: pygame.event.Event) -> bool:
    return event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE)


def _await_approval(window: pygame.Surface, frame: Frame, server: Server) -> str | None:
    """Register with the server and show a waiting screen until the admin accepts this client.

    Returns the id of the snapshot to continue from, or None if the server has none for us.
    """
    code = None
    next_poll = 0.0
    frame.draw_message(window, "CONNECTING", "TO THE SERVER")
    while True:
        if any(_quit_requested(event) for event in pygame.event.get()):
            raise SystemExit
        if time.monotonic() >= next_poll:
            next_poll = time.monotonic() + _POLL_SECONDS
            try:
                if code is None:
                    code = server.register()
                status, start = server.poll()
            except urllib.error.HTTPError as error:
                if error.code == 401:  # the server no longer knows us, e.g. its database was reset
                    code = None
                frame.draw_message(window, "SERVER ERROR", f"{error.code} {error.reason}"[:28].upper())
            except OSError:
                frame.draw_message(window, "NO SERVER", "RETRYING")
            else:
                if status == "accepted":
                    return start
                if status != "pending":
                    raise SystemExit(f"The server {status} this client.")
                frame.draw_message(window, "WAITING FOR ADMIN", f"CODE {code}")
        pygame.display.flip()
        pygame.time.wait(50)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", nargs="?", default="pokemon-firered.gba")
    parser.add_argument("--data", type=Path, default=Path("data"), help="directory for the cartridge save file")
    parser.add_argument("--phone-number", default="7653", help="the hotline's extension shown on screen")
    parser.add_argument("--size", default="1280x720", help="window size, WIDTHxHEIGHT")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--state", type=Path, help="start from this state file (see dpp.start_state)")
    parser.add_argument(
        "--server",
        metavar="URL",
        help="wait for this server's admin to accept us, continue from the snapshot it names (if it has none, "
        "from --state or power-on), and upload snapshots to it",
    )
    parser.add_argument("--upload-interval", type=float, default=10, help="minutes between uploads to the server")
    parser.add_argument("--name", default=socket.gethostname(), help="what the server's admin page calls this client")
    parser.add_argument("--demo-stats", action="store_true", help="show made-up badges and party (layout preview)")
    parser.add_argument("--screenshot", type=Path, help="run --frames frames unthrottled, save the window as PNG, exit")
    parser.add_argument("--frames", type=int, default=2400)
    args = parser.parse_args()

    args.data.mkdir(parents=True, exist_ok=True)
    emu = Emulator(args.rom, args.data / "firered.sav")
    if args.state:
        emu.load_state(zlib.decompress(args.state.read_bytes()))
        print(f"started from {args.state}")

    pygame.init()
    if args.fullscreen:
        window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
    else:
        window = pygame.display.set_mode(tuple(int(n) for n in args.size.split("x")))
    pygame.display.set_caption("DECT plays Pokémon")
    frame = Frame(window.get_size(), args.phone_number, read_badge_icons(emu), lambda species: read_mon_icon(emu, species))
    inputs = InputQueue()

    if args.screenshot:
        for _ in range(args.frames):
            emu.run_frame()
        inputs.press_phone_key("5")
        frame.draw(window, emu.framebuffer, DEMO_STATS if args.demo_stats else read_stats(emu), inputs.next_frame())
        pygame.image.save(window, args.screenshot)
        return

    server = uplink = None
    if args.server:
        server = Server(args.server, args.name)
        start_snapshot = _await_approval(window, frame, server)
        if start_snapshot:
            emu.load_state(server.fetch_state(start_snapshot))
            print(f"continuing from server snapshot {start_snapshot}, frame {emu.frame}")
        uplink = Uplink(server, emu, parent=start_snapshot)

    clock = pygame.time.Clock()
    next_upload = time.monotonic() + args.upload_interval * 60
    while True:
        for event in pygame.event.get():
            if _quit_requested(event):
                if uplink:
                    uplink.upload()
                    if not server.flush(_FINAL_UPLOAD_SECONDS):
                        print("the final snapshot did not reach the server")
                return
            if event.type == pygame.KEYDOWN and event.key in _PHONE_KEYS:
                inputs.press_phone_key(_PHONE_KEYS[event.key])

        held = inputs.next_frame()
        if uplink:
            uplink.record(held)
        emu.run_frame(held)
        stats = DEMO_STATS if args.demo_stats else read_stats(emu)
        frame.draw(window, emu.framebuffer, stats, held, server.sync_status if server else "ok")
        pygame.display.flip()

        if uplink and time.monotonic() >= next_upload:
            uplink.upload()
            next_upload = time.monotonic() + args.upload_interval * 60
        clock.tick(Emulator.FPS)


if __name__ == "__main__":
    main()
