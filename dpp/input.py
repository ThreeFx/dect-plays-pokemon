"""GBA buttons, the phone-key bindings, and a thread-safe queue that turns presses into per-frame key masks."""

from __future__ import annotations

import enum
import threading
from collections import deque


class Button(enum.IntFlag):
    """GBA buttons; values are the bit masks of the GBA key register."""

    A = 1 << 0
    B = 1 << 1
    SELECT = 1 << 2
    START = 1 << 3
    RIGHT = 1 << 4
    LEFT = 1 << 5
    UP = 1 << 6
    DOWN = 1 << 7
    R = 1 << 8
    L = 1 << 9


# Phone key -> GBA button. Keys without an entry do nothing.
PHONE_KEYS: dict[str, Button] = {
    "1": Button.B,
    "2": Button.UP,
    "4": Button.LEFT,
    "5": Button.A,
    "6": Button.RIGHT,
    "7": Button.SELECT,
    "8": Button.DOWN,
    "9": Button.START,
}

# A phone key press has no duration, so every press holds the button for
# HOLD_FRAMES and then releases it for GAP_FRAMES before the next press starts.
HOLD_FRAMES = 8
GAP_FRAMES = 4


class InputQueue:
    """Collects button presses from any thread; the emulator loop drains one key mask per frame."""

    def __init__(self, hold_frames: int = HOLD_FRAMES, gap_frames: int = GAP_FRAMES, max_pending: int = 32):
        self._hold = hold_frames
        self._gap = gap_frames
        self._pending: deque[Button] = deque(maxlen=max_pending)
        self._lock = threading.Lock()
        self._current = Button(0)
        self._frames_left = 0
        self._in_gap = False

    def press(self, button: Button) -> None:
        """Queue one press. When the queue is full the oldest pending press is dropped."""
        with self._lock:
            self._pending.append(button)

    def press_phone_key(self, key: str) -> Button | None:
        """Queue the button bound to a phone key; returns it, or None if the key is unbound."""
        button = PHONE_KEYS.get(key)
        if button is not None:
            self.press(button)
        return button

    def next_frame(self) -> Button:
        """Return the key mask to hold during the next emulated frame."""
        if self._frames_left == 0:
            if self._in_gap or not self._current:
                self._in_gap = False
                with self._lock:
                    self._current = self._pending.popleft() if self._pending else Button(0)
                self._frames_left = self._hold if self._current else 0
            else:
                self._in_gap = True
                self._current = Button(0)
                self._frames_left = self._gap
        if self._frames_left:
            self._frames_left -= 1
        return self._current
