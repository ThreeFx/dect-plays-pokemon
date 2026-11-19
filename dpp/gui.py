"""The beamer window: the game screen framed by phone number, key bindings, party and badges."""

from __future__ import annotations

import colorsys
import math
from pathlib import Path

import pygame

from .emulator import Emulator
from .firered import BADGE_ICON_SIZE, GameStats, PartyMon
from .input import PHONE_KEYS, Button

_FONT = Path(__file__).parent / "assets" / "PressStart2P-Regular.ttf"

# The canvas is 320 x 180 units (16:9). The game takes 240 x 160 of it, so one
# unit is one GBA pixel times an integer scale (6 on a 1080p beamer).
CANVAS = (320, 180)

BACKGROUND = (14, 16, 26)
PANEL = (27, 31, 48)
KEY = (48, 55, 82)
KEY_UNBOUND = (33, 38, 58)
TEXT = (238, 236, 226)
DIM = (120, 128, 158)
ACCENT = (240, 88, 48)
HP_HIGH = (88, 208, 96)
HP_MID = (240, 200, 56)
HP_LOW = (232, 64, 56)
BADGE_MISSING = (52, 58, 86)

# The game draws all badges in silver; these are their usual colours, in badge
# order. None is the Rainbow Badge, which gets a colour wheel instead.
_BADGE_TINTS = [
    (200, 204, 216),
    (88, 168, 255),
    (255, 190, 56),
    None,
    (255, 112, 176),
    (248, 204, 72),
    (255, 88, 60),
    (96, 208, 104),
]

_ARROWS = {Button.UP: 0, Button.RIGHT: 90, Button.DOWN: 180, Button.LEFT: 270}
_ARROW_SHAPE = [(0, -1), (1, 0.05), (0.38, 0.05), (0.38, 1), (-0.38, 1), (-0.38, 0.05), (-1, 0.05)]


def _polygon(shape, center, radius, degrees=0.0):
    """Scale, rotate and move a shape given in a -1..1 square."""
    sin, cos = math.sin(math.radians(degrees)), math.cos(math.radians(degrees))
    return [(center[0] + radius * (x * cos - y * sin), center[1] + radius * (x * sin + y * cos)) for x, y in shape]


def _tint(icon: bytes, badge: int) -> bytes:
    """Colour a silver badge icon (RGBA pixels). Multiplying keeps its shading and black outline."""
    out = bytearray(icon)
    for pixel in range(len(out) // 4):
        tint = _BADGE_TINTS[badge]
        if tint is None:
            x, y = pixel % BADGE_ICON_SIZE - 7.5, pixel // BADGE_ICON_SIZE - 7.5
            tint = [round(c * 255) for c in colorsys.hsv_to_rgb(math.atan2(y, x) / math.tau % 1, 0.6, 1)]
        for channel in range(3):
            out[pixel * 4 + channel] = out[pixel * 4 + channel] * tint[channel] // 255
    return bytes(out)


class Frame:
    """Draws the whole window onto a pygame surface."""

    def __init__(self, window_size: tuple[int, int], phone_number: str, badge_icons: list[bytes]):
        """badge_icons are the eight icons from firered.read_badge_icons()."""
        self.unit = u = max(1, min(window_size[0] // CANVAS[0], window_size[1] // CANVAS[1]))
        self._origin = ((window_size[0] - CANVAS[0] * u) // 2, (window_size[1] - CANVAS[1] * u) // 2)
        self._phone_number = phone_number
        # Press Start 2P is drawn on an 8 px grid; these sizes land on it when u is 6.
        self._small = pygame.font.Font(_FONT, round(u * 8 / 3))
        self._medium = pygame.font.Font(_FONT, u * 4)
        self._large = pygame.font.Font(_FONT, u * 8)
        self._huge = pygame.font.Font(_FONT, u * 16)
        self._panels = pygame.Surface((CANVAS[0] * u, CANVAS[1] * u))

        # Badges keep whole game pixels: the largest integer scale that fits the strip.
        size = BADGE_ICON_SIZE * max(1, 14 * u // BADGE_ICON_SIZE)
        self._badges = []  # (earned, missing) surface per badge
        for index, icon in enumerate(badge_icons):
            earned = pygame.image.frombuffer(_tint(icon, index), (BADGE_ICON_SIZE, BADGE_ICON_SIZE), "RGBA")
            earned = pygame.transform.scale(earned, (size, size))
            missing = pygame.mask.from_surface(earned).to_surface(setcolor=BADGE_MISSING, unsetcolor=(0, 0, 0, 0))
            self._badges.append((earned, missing))
        self._drawn: tuple[GameStats, Button] | None = None

    def draw(self, window: pygame.Surface, framebuffer, stats: GameStats, held: Button) -> None:
        """Draw one frame: framebuffer is the emulator's screen, held the buttons currently pressed."""
        if (stats, held) != self._drawn:
            self._draw_panels(stats, held)
            self._drawn = (stats, held)
        window.blit(self._panels, self._origin)
        game = pygame.image.frombuffer(framebuffer, (Emulator.WIDTH, Emulator.HEIGHT), "RGBX")
        window.blit(pygame.transform.scale(game, self._rect(0, 0, 240, 160).size), self._origin)

    def _rect(self, x: float, y: float, w: float, h: float) -> pygame.Rect:
        u = self.unit
        return pygame.Rect(round(x * u), round(y * u), round(w * u), round(h * u))

    def _text(self, font: pygame.font.Font, text: str, colour, **anchor) -> None:
        """Draw text; anchor is one pygame Rect keyword in units, e.g. midtop=(280, 6)."""
        rendered = font.render(text, True, colour)
        (name, (x, y)), = anchor.items()
        self._panels.blit(rendered, rendered.get_rect(**{name: (round(x * self.unit), round(y * self.unit))}))

    def _panel(self, x: float, y: float, w: float, h: float, colour=PANEL) -> None:
        pygame.draw.rect(self._panels, colour, self._rect(x, y, w, h), border_radius=self.unit * 2)

    def _draw_panels(self, stats: GameStats, held: Button) -> None:
        self._panels.fill(BACKGROUND)
        self._draw_phone_number()
        self._draw_keypad(held)
        self._draw_party(stats.party)
        self._draw_badges(stats.badges)

    def _draw_phone_number(self) -> None:
        self._panel(242, 2, 76, 32)
        self._text(self._small, "CALL TO PLAY", DIM, midtop=(280, 6))
        self._text(self._huge, self._phone_number, ACCENT, midtop=(280.5, 13))

    def _draw_keypad(self, held: Button) -> None:
        self._panel(242, 36, 76, 68)
        self._text(self._small, "PHONE KEYS", DIM, midtop=(280, 40))
        u = self.unit
        for index in range(9):
            digit = str(index + 1)
            button = PHONE_KEYS.get(digit)
            x, y = 245 + (index % 3) * 24, 47 + (index // 3) * 18.5
            pressed = button is not None and button in held
            self._panel(x, y, 22, 16.5, ACCENT if pressed else KEY if button else KEY_UNBOUND)
            self._text(self._small, digit, TEXT if pressed else DIM, topleft=(x + 2, y + 2))
            centre = (x + 11.5, y + 9)
            if button in _ARROWS:
                arrow = _polygon(_ARROW_SHAPE, (centre[0] * u, centre[1] * u), 4.5 * u, _ARROWS[button])
                pygame.draw.polygon(self._panels, TEXT, arrow)
            elif button in (Button.A, Button.B):
                self._text(self._large, button.name, TEXT, center=(centre[0] + 0.5, centre[1] + 0.5))
            elif button is not None:
                self._text(self._small, button.name, TEXT, midbottom=(x + 11, y + 14.5))

    def _draw_party(self, party: tuple[PartyMon, ...]) -> None:
        self._panel(242, 106, 76, 72)
        self._text(self._small, "PARTY", DIM, midtop=(280, 110))
        for slot in range(6):
            y = 116.5 + slot * 10
            if slot >= len(party):
                pygame.draw.rect(self._panels, KEY_UNBOUND, self._rect(245, y + 1, 70, 7), border_radius=self.unit)
                continue
            mon = party[slot]
            fainted = mon.hp == 0
            self._text(self._small, mon.nickname, DIM if fainted else TEXT, topleft=(245, y))
            self._text(self._small, f"L{mon.level}", DIM, topright=(315, y))
            ratio = mon.hp / mon.max_hp if mon.max_hp else 0
            colour = HP_HIGH if ratio > 0.5 else HP_MID if ratio > 0.2 else HP_LOW
            pygame.draw.rect(self._panels, KEY_UNBOUND, self._rect(245, y + 4.5, 46, 2.5), border_radius=self.unit)
            if mon.hp:
                bar = self._rect(245, y + 4.5, max(2.5, 46 * ratio), 2.5)
                pygame.draw.rect(self._panels, colour, bar, border_radius=self.unit)
            self._text(self._small, f"{mon.hp}/{mon.max_hp}", DIM, topright=(315, y + 4.4))

    def _draw_badges(self, badges: tuple[bool, ...]) -> None:
        self._panel(2, 162, 236, 16)
        self._text(self._small, "BADGES", DIM, midleft=(7, 170.3))
        for index, earned in enumerate(badges):
            icon = self._badges[index][0 if earned else 1]
            centre = ((46 + index * 21) * self.unit, 170 * self.unit)
            self._panels.blit(icon, icon.get_rect(center=centre))
        self._text(self._medium, f"{sum(badges)}/8", TEXT, midright=(233, 170.3))
