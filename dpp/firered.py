"""Reads game facts out of Pokémon FireRed's RAM (US releases, game code BPRE)."""

from __future__ import annotations

from dataclasses import dataclass

from .emulator import Emulator

BADGE_NAMES = ("Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh", "Volcano", "Earth")

# Symbols from the pret/pokefirered decompilation.
_SAVE_BLOCK_1_PTR = 0x03005008  # the save block moves around in EWRAM, so the game keeps a pointer
_PLAYER_PARTY_COUNT = 0x02024029
_PLAYER_PARTY = 0x02024284
_FLAGS_OFFSET = 0xEE0  # event flag bit array inside save block 1
_FLAG_BADGE_1 = 0x820  # the eight badge flags are consecutive
_MON_SIZE = 100
_EWRAM = range(0x02000000, 0x02040000)

_CHARSET = {0x00: " ", 0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-", 0xB8: ",", 0xBA: "/"}
_CHARSET |= {0xA1 + i: str(i) for i in range(10)}
_CHARSET |= {0xBB + i: chr(ord("A") + i) for i in range(26)}
_CHARSET |= {0xD5 + i: chr(ord("a") + i) for i in range(26)}
_TERMINATOR = 0xFF


@dataclass(frozen=True)
class PartyMon:
    nickname: str
    level: int
    hp: int
    max_hp: int


@dataclass(frozen=True)
class GameStats:
    badges: tuple[bool, ...] = (False,) * 8
    party: tuple[PartyMon, ...] = ()


def decode_text(raw: bytes) -> str:
    """Decode the game's own character encoding; unknown characters become '?'."""
    text = []
    for byte in raw:
        if byte == _TERMINATOR:
            break
        text.append(_CHARSET.get(byte, "?"))
    return "".join(text)


def read_stats(emu: Emulator) -> GameStats:
    """Badges and party as the game currently holds them; empty until a game is running."""
    save_block_1 = emu.read_u32(_SAVE_BLOCK_1_PTR)
    if save_block_1 not in _EWRAM:
        return GameStats()

    badge_bits = emu.read_u8(save_block_1 + _FLAGS_OFFSET + _FLAG_BADGE_1 // 8)
    badges = tuple(bool(badge_bits >> i & 1) for i in range(8))

    party = []
    for slot in range(min(emu.read_u8(_PLAYER_PARTY_COUNT), 6)):
        mon = emu.read(_PLAYER_PARTY + slot * _MON_SIZE, _MON_SIZE)
        party.append(
            PartyMon(
                nickname=decode_text(mon[8:18]),
                level=mon[84],
                hp=int.from_bytes(mon[86:88], "little"),
                max_hp=int.from_bytes(mon[88:90], "little"),
            )
        )
    return GameStats(badges, tuple(party))


DEMO_STATS = GameStats(
    badges=(True, True, True, False, False, False, False, False),
    party=(
        PartyMon("CHARMELEON", 27, 71, 78),
        PartyMon("PIDGEOTTO", 24, 29, 66),
        PartyMon("PIKACHU", 22, 9, 54),
        PartyMon("GYARADOS", 21, 0, 70),
    ),
)
