import hashlib
import random

from dpp.emulator import Emulator
from dpp.firered import (
    BADGE_ICON_SIZE,
    MON_ICON_SIZE,
    GameStats,
    _species,
    decode_text,
    read_badge_icons,
    read_mon_icon,
    read_stats,
)
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


def test_badge_icons_come_out_of_the_rom(emu):
    icons = read_badge_icons(emu)
    assert len(icons) == 8
    assert len(set(icons)) == 8
    for icon in icons:
        assert len(icon) == BADGE_ICON_SIZE * BADGE_ICON_SIZE * 4
        alpha = icon[3::4]
        assert alpha[0] == 0, "corner should be transparent"
        assert 60 < sum(a == 255 for a in alpha) < 256, "icon should be a shape, not a filled or empty square"


def test_mon_icons_come_out_of_the_rom(emu):
    bulbasaur, pikachu = read_mon_icon(emu, 1), read_mon_icon(emu, 25)
    assert bulbasaur != pikachu
    for icon in (bulbasaur, pikachu):
        assert len(icon) == MON_ICON_SIZE * MON_ICON_SIZE * 4
        alpha = icon[3::4]
        assert alpha[0] == 0, "corner should be transparent"
        assert 100 < sum(a == 255 for a in alpha) < 900
    assert read_mon_icon(emu, 0) is None
    assert read_mon_icon(emu, 5000) is None


_BLOCK_ORDERS = "GAEM GAME GEAM GEMA GMAE GMEA AGEM AGME AEGM AEMG AMGE AMEG EGAM EGMA EAGM EAMG EMGA EMAG MGAE MGEA MAGE MAEG MEGA MEAG"


def _party_mon(personality: int, ot_id: int, species: int, egg: bool = False) -> bytes:
    """A 100-byte party Pokémon with only the fields that decide its species filled in."""
    key = personality ^ ot_id
    blocks = [bytes(12)] * 4
    growth = _BLOCK_ORDERS.split()[personality % 24].index("G")
    blocks[growth] = (species ^ key).to_bytes(4, "little") + bytes(8)
    header = personality.to_bytes(4, "little") + ot_id.to_bytes(4, "little") + bytes(11) + bytes([4 if egg else 0]) + bytes(12)
    return header + b"".join(blocks) + bytes(20)


def test_species_is_decrypted_from_the_right_block():
    for personality in range(1000, 1024):  # every block order once
        assert _species(_party_mon(personality, 0xDEADBEEF, 150)) == 150
    assert _species(_party_mon(7, 1, 150, egg=True)) == 412


def test_decode_text():
    assert decode_text(bytes([0xBC, 0xCF, 0xC6, 0xBC, 0xBB, 0xFF, 0x00, 0x00])) == "BULBA"
    assert decode_text(bytes([0xCC, 0xE9, 0xD8, 0xED, 0x00, 0xA3, 0xFF])) == "Rudy 2"


def test_start_state_is_in_oaks_lab_before_the_starter_choice(emu, rom):
    from dpp.firered import read_player_name, read_position
    from dpp.start_state import create

    emu.load_state(create(rom, "DECT", "GSM"))
    assert read_player_name(emu) == "DECT"
    assert read_position(emu) == (4, 3, 6, 4)
    assert read_stats(emu).party == ()
