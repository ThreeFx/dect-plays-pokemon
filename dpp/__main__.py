"""Run the game window: python -m dpp [ROM]"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pygame

from .emulator import Emulator
from .firered import DEMO_STATS, read_stats
from .gui import Frame
from .input import InputQueue
from .snapshots import SnapshotStore

# Keyboard stand-ins for the phone keys, until the phone part exists.
_PHONE_KEYS = {getattr(pygame, f"K_{d}"): str(d) for d in range(1, 10)}
_PHONE_KEYS |= {getattr(pygame, f"K_KP{d}"): str(d) for d in range(1, 10)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", nargs="?", default="pokemon-firered.gba")
    parser.add_argument("--data", type=Path, default=Path("data"), help="directory for the save file and snapshots")
    parser.add_argument("--phone-number", default="7653", help="the hotline's extension shown on screen")
    parser.add_argument("--size", default="1280x720", help="window size, WIDTHxHEIGHT")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--snapshot-interval", type=float, default=60, help="seconds between automatic snapshots")
    parser.add_argument("--resume", action="store_true", help="start from the latest snapshot")
    parser.add_argument("--demo-stats", action="store_true", help="show made-up badges and party (layout preview)")
    parser.add_argument("--screenshot", type=Path, help="run --frames frames unthrottled, save the window as PNG, exit")
    parser.add_argument("--frames", type=int, default=2400)
    args = parser.parse_args()

    args.data.mkdir(parents=True, exist_ok=True)
    emu = Emulator(args.rom, args.data / "firered.sav")
    snapshots = SnapshotStore(args.data / "snapshots")
    if args.resume and (latest := snapshots.latest()):
        snapshots.load(emu, latest)
        print(f"resumed from {latest}")

    pygame.init()
    if args.fullscreen:
        window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
    else:
        window = pygame.display.set_mode(tuple(int(n) for n in args.size.split("x")))
    pygame.display.set_caption("DECT plays Pokémon")
    frame = Frame(window.get_size(), args.phone_number)
    inputs = InputQueue()

    if args.screenshot:
        for _ in range(args.frames):
            emu.run_frame()
        inputs.press_phone_key("5")
        frame.draw(window, emu.framebuffer, DEMO_STATS if args.demo_stats else read_stats(emu), inputs.next_frame())
        pygame.image.save(window, args.screenshot)
        return

    clock = pygame.time.Clock()
    next_snapshot = time.monotonic() + args.snapshot_interval
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                print(f"saved {snapshots.save(emu)}")
                return
            if event.type == pygame.KEYDOWN:
                if event.key in _PHONE_KEYS:
                    inputs.press_phone_key(_PHONE_KEYS[event.key])
                elif event.key == pygame.K_F5:
                    print(f"saved {snapshots.save(emu)}")
                elif event.key == pygame.K_F9 and (latest := snapshots.latest()):
                    snapshots.load(emu, latest)
                    print(f"rolled back to {latest}")

        held = inputs.next_frame()
        emu.run_frame(held)
        frame.draw(window, emu.framebuffer, DEMO_STATS if args.demo_stats else read_stats(emu), held)
        pygame.display.flip()

        if time.monotonic() >= next_snapshot:
            snapshots.save(emu)
            next_snapshot = time.monotonic() + args.snapshot_interval
        clock.tick(Emulator.FPS)


if __name__ == "__main__":
    main()
