"""Reads game facts and graphics out of Pokémon FireRed (US releases, game code BPRE)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # keeps this module usable where mGBA is not installed, i.e. on the server
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

# Graphics are read from the ROM, where addresses differ between revisions:
# ROM revision -> pokefirered symbol -> address.
_ROM_REVISION = 0x080000BC
_ROM_SYMBOLS = {
    0: {
        "sKantoTrainerCardBadges_Gfx": 0x083CD5E8,
        "sKantoTrainerCardBadges_Pal": 0x083CD2E0,
        "gMonIconPalettes": 0x083D3740,
        "gMonIconTable": 0x083D37A0,
        "gMonIconPaletteIndices": 0x083D3E80,
    },
    1: {
        "sKantoTrainerCardBadges_Gfx": 0x083CD658,
        "sKantoTrainerCardBadges_Pal": 0x083CD350,
        "gMonIconPalettes": 0x083D37B0,
        "gMonIconTable": 0x083D3810,
        "gMonIconPaletteIndices": 0x083D3EF0,
    },
}
BADGE_ICON_SIZE = 16
MON_ICON_SIZE = 32
_SPECIES_COUNT = 440  # entries in the icon tables
_SPECIES_EGG = 412

# A party Pokémon keeps its species inside 48 encrypted bytes made of four
# 12-byte blocks whose order depends on its personality value. This is the
# position of the block that starts with the species ("growth") for each order.
_GROWTH_BLOCK = (0, 0, 0, 0, 0, 0, 1, 1, 2, 3, 2, 3, 1, 1, 2, 3, 2, 3, 1, 1, 2, 3, 2, 3)

_CHARSET = {0x00: " ", 0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-", 0xB8: ",", 0xBA: "/"}
_CHARSET |= {0xA1 + i: str(i) for i in range(10)}
_CHARSET |= {0xBB + i: chr(ord("A") + i) for i in range(26)}
_CHARSET |= {0xD5 + i: chr(ord("a") + i) for i in range(26)}
_TERMINATOR = 0xFF


@dataclass(frozen=True)
class PartyMon:
    species: int  # national-order index as the game stores it; eggs count as their own species
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


def _species(mon: bytes) -> int:
    """The species of a 100-byte party Pokémon."""
    if mon[19] & 0b100:
        return _SPECIES_EGG
    personality = int.from_bytes(mon[0:4], "little")
    key = personality ^ int.from_bytes(mon[4:8], "little")
    block = 32 + 12 * _GROWTH_BLOCK[personality % 24]
    return (int.from_bytes(mon[block : block + 4], "little") ^ key) & 0xFFFF


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
                species=_species(mon),
                nickname=decode_text(mon[8:18]),
                level=mon[84],
                hp=int.from_bytes(mon[86:88], "little"),
                max_hp=int.from_bytes(mon[88:90], "little"),
            )
        )
    return GameStats(badges, tuple(party))


class Rom:
    """A ROM file, readable at the addresses the GBA maps it to.

    The graphics below can be read from this or from a running Emulator.
    """

    _BASE = 0x08000000

    def __init__(self, path: str | Path):
        self._data = Path(path).read_bytes()

    @property
    def game_code(self) -> str:
        return "AGB-" + self._data[0xAC:0xB0].decode("ascii", "replace")

    def read(self, address: int, length: int) -> bytes:
        offset = address - self._BASE
        if offset < 0 or offset + length > len(self._data):
            raise ValueError(f"cannot read {length} bytes at {address:#010x}")
        return self._data[offset : offset + length]

    def read_u8(self, address: int) -> int:
        return self.read(address, 1)[0]

    def read_u16(self, address: int) -> int:
        return int.from_bytes(self.read(address, 2), "little")

    def read_u32(self, address: int) -> int:
        return int.from_bytes(self.read(address, 4), "little")


def _lz77_decompress(rom: Emulator | Rom, address: int) -> bytes:
    """Decompress data stored in the GBA BIOS's LZ77 format."""
    header = rom.read(address, 4)
    if header[0] != 0x10:
        raise ValueError(f"no LZ77 data at {address:#010x}")
    size = int.from_bytes(header[1:], "little")
    data = rom.read(address + 4, size * 9 // 8 + 8)  # worst case: nothing compresses
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


def _rom_symbols(rom: Emulator | Rom) -> dict[str, int]:
    revision = rom.read_u8(_ROM_REVISION)
    if rom.game_code != "AGB-BPRE" or revision not in _ROM_SYMBOLS:
        raise ValueError(f"unsupported ROM {rom.game_code} revision {revision}; need US FireRed (BPRE) 1.0 or 1.1")
    return _ROM_SYMBOLS[revision]


def _read_palette(rom: Emulator | Rom, address: int) -> list[bytes]:
    """A 16-colour palette as RGBA values; colour 0 is transparent."""
    palette = []
    for i in range(16):
        colour = rom.read_u16(address + 2 * i)  # 15-bit BGR
        red, green, blue = (channel * 255 // 31 for channel in (colour & 31, colour >> 5 & 31, colour >> 10 & 31))
        palette.append(bytes((red, green, blue, 255 if i else 0)))
    return palette


def _tiles_to_rgba(tiles: bytes, palette: list[bytes], size: int, first_tile: int, tiles_per_row: int) -> bytes:
    """Cut a size x size picture out of a sheet of 8x8 tiles with 4 bits per pixel."""
    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            tile = first_tile + (y // 8) * tiles_per_row + x // 8
            pair = tiles[tile * 32 + (y % 8) * 4 + (x % 8) // 2]  # two pixels per byte, left one in the low half
            pixels += palette[pair >> 4 if x % 2 else pair & 0xF]
    return bytes(pixels)


def read_badge_icons(rom: Emulator | Rom) -> list[bytes]:
    """The eight badge icons as the game draws them, each BADGE_ICON_SIZE square RGBA pixels."""
    symbols = _rom_symbols(rom)
    tiles = _lz77_decompress(rom, symbols["sKantoTrainerCardBadges_Gfx"])  # a sheet 16 tiles wide, 2 x 2 tiles per badge
    palette = _read_palette(rom, symbols["sKantoTrainerCardBadges_Pal"])
    return [_tiles_to_rgba(tiles, palette, BADGE_ICON_SIZE, badge * 2, 16) for badge in range(8)]


def read_mon_icon(rom: Emulator | Rom, species: int) -> bytes | None:
    """A species' party-menu icon as MON_ICON_SIZE square RGBA pixels; None for an unknown species."""
    if not 0 < species < _SPECIES_COUNT:
        return None
    symbols = _rom_symbols(rom)
    # Each icon is two animation frames of 4 x 4 tiles, stored uncompressed; take the first.
    tiles = rom.read(rom.read_u32(symbols["gMonIconTable"] + 4 * species), 16 * 32)
    palette_index = rom.read_u8(symbols["gMonIconPaletteIndices"] + species)
    palette = _read_palette(rom, symbols["gMonIconPalettes"] + 32 * palette_index)
    return _tiles_to_rgba(tiles, palette, MON_ICON_SIZE, 0, 4)


DEMO_STATS = GameStats(
    badges=(True, True, True, False, False, False, False, False),
    party=(
        PartyMon(5, "CHARMELEON", 27, 71, 78),
        PartyMon(17, "PIDGEOTTO", 24, 29, 66),
        PartyMon(25, "PIKACHU", 22, 9, 54),
        PartyMon(130, "GYARADOS", 21, 0, 70),
    ),
)
