import hashlib
import random

from dpp.emulator import Emulator
from dpp.firered import GameStats, decode_text, read_stats
from dpp.input import Button


def _ram_digest(emu: Emulator) -> str:
    return hashlib.sha1(emu.read(0x02000000, 0x40000) + emu.read(0x03000000, 0x8000)).hexdigest()


def _play(emu: Emulator, frames: int, seed: int) -> None:
    rng = random.Random(seed)
    for i in range(frames):
        emu.run_frame(rng.choice([Button.A, Button.START, Button.DOWN]) if i // 10 % 2 else 0)


def test_boots_the_expected_game(emu):
    assert emu.game_code == "AGB-BPRE"
    assert emu.read(0x080000A0, 12) == b"POKEMON FIRE"
    assert len(emu.framebuffer) == Emulator.WIDTH * Emulator.HEIGHT * 4


def test_state_plus_inputs_replays_identically(emu):
    _play(emu, 600, seed=0)
    state = emu.save_state()
    start = emu.frame

    _play(emu, 1500, seed=1)
    first = _ram_digest(emu)

    emu.load_state(state)
    assert emu.frame == start
    _play(emu, 1500, seed=1)
    assert _ram_digest(emu) == first

    emu.load_state(state)
    _play(emu, 1500, seed=2)
    assert _ram_digest(emu) != first


def test_stats_are_empty_before_a_game_is_running(emu):
    assert read_stats(emu) == GameStats()


def test_decode_text():
    assert decode_text(bytes([0xBC, 0xCF, 0xC6, 0xBC, 0xBB, 0xFF, 0x00, 0x00])) == "BULBA"
    assert decode_text(bytes([0xCC, 0xE9, 0xD8, 0xED, 0x00, 0xA3, 0xFF])) == "Rudy 2"
