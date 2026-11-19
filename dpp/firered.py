"""Reads game facts and graphics out of Pokémon FireRed (US releases, game code BPRE)."""

from __future__ import annotations

from dataclasses import dataclass

from .emulator import Emulator

BADGE_NAMES = ("Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh", "Volcano", "Earth")

# Symbols from the pret/pokefirered decompilation.
_SAVE_BLOCK_1_PTR = 0x03005008  # the save blocks move around in EWRAM, so the game keeps pointers
_SAVE_BLOCK_2_PTR = 0x0300500C
_PLAYER_PARTY_COUNT = 0x02024029
_PLAYER_PARTY = 0x02024284
_FLAGS_OFFSET = 0xEE0  # event flag bit array inside save block 1
_FLAG_BADGE_1 = 0x820  # the eight badge flags are consecutive
_MON_SIZE = 100
_EWRAM = range(0x02000000, 0x02040000)

# The badge icons live in the ROM as part of the trainer card: an LZ77-compressed
# sheet of 4bpp tiles and a palette. ROM revision -> (sKantoTrainerCardBadges_Gfx,
# sKantoTrainerCardBadges_Pal).
_ROM_REVISION = 0x080000BC
_BADGE_GRAPHICS = {0: (0x083CD5E8, 0x083CD2E0), 1: (0x083CD658, 0x083CD350)}
_SHEET_TILES_PER_ROW = 16
BADGE_ICON_SIZE = 16

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


def read_player_name(emu: Emulator) -> str:
    """The player's name; empty until a game is running."""
    save_block_2 = emu.read_u32(_SAVE_BLOCK_2_PTR)
    return decode_text(emu.read(save_block_2, 8)) if save_block_2 in _EWRAM else ""


def read_position(emu: Emulator) -> tuple[int, int, int, int] | None:
    """Where the player stands as (map group, map number, x, y); None until a game is running."""
    save_block_1 = emu.read_u32(_SAVE_BLOCK_1_PTR)
    if save_block_1 not in _EWRAM:
        return None
    raw = emu.read(save_block_1, 6)
    x, y = (int.from_bytes(raw[i : i + 2], "little", signed=True) for i in (0, 2))
    return raw[4], raw[5], x, y


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


def _lz77_decompress(emu: Emulator, address: int) -> bytes:
    """Decompress data stored in the GBA BIOS's LZ77 format."""
    header = emu.read(address, 4)
    if header[0] != 0x10:
        raise ValueError(f"no LZ77 data at {address:#010x}")
    size = int.from_bytes(header[1:], "little")
    data = emu.read(address + 4, size * 9 // 8 + 8)  # worst case: nothing compresses
    out = bytearray()
    pos = 0
    while len(out) < size:
        flags = data[pos]
        pos += 1
        for bit in range(7, -1, -1):
            if len(out) >= size:
                break
            if flags >> bit & 1:  # copy from earlier output
                length = (data[pos] >> 4) + 3
                distance = ((data[pos] & 0xF) << 8 | data[pos + 1]) + 1
                pos += 2
                for _ in range(length):
                    out.append(out[-distance])
            else:
                out.append(data[pos])
                pos += 1
    return bytes(out[:size])


def read_badge_icons(emu: Emulator) -> list[bytes]:
    """The eight badge icons as the game draws them, each BADGE_ICON_SIZE square RGBA pixels."""
    revision = emu.read_u8(_ROM_REVISION)
    if emu.game_code != "AGB-BPRE" or revision not in _BADGE_GRAPHICS:
        raise ValueError(f"unsupported ROM {emu.game_code} revision {revision}; need US FireRed (BPRE) 1.0 or 1.1")
    graphics, palette_address = _BADGE_GRAPHICS[revision]
    tiles = _lz77_decompress(emu, graphics)

    palette = []
    for i in range(16):
        colour = emu.read_u16(palette_address + 2 * i)  # 15-bit BGR
        red, green, blue = (channel * 255 // 31 for channel in (colour & 31, colour >> 5 & 31, colour >> 10 & 31))
        palette.append(bytes((red, green, blue, 255 if i else 0)))  # colour 0 is transparent

    icons = []
    for badge in range(8):
        pixels = bytearray()
        for y in range(BADGE_ICON_SIZE):
            for x in range(BADGE_ICON_SIZE):
                tile = (y // 8) * _SHEET_TILES_PER_ROW + badge * 2 + x // 8
                pair = tiles[tile * 32 + (y % 8) * 4 + (x % 8) // 2]  # two pixels per byte, left one in the low half
                pixels += palette[pair >> 4 if x % 2 else pair & 0xF]
        icons.append(bytes(pixels))
    return icons


DEMO_STATS = GameStats(
    badges=(True, True, True, False, False, False, False, False),
    party=(
        PartyMon("CHARMELEON", 27, 71, 78),
        PartyMon("PIDGEOTTO", 24, 29, 66),
        PartyMon("PIKACHU", 22, 9, 54),
        PartyMon("GYARADOS", 21, 0, 70),
    ),
)
