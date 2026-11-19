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

# A phone key press has no duration, so at a relaxed pace every press holds the
# button for HOLD_FRAMES and then releases it for GAP_FRAMES. When presses
# arrive faster than that, they are played shorter, so that every press is over
# within DRAIN_FRAMES of arriving. The shortest press is one frame held and one
# released, so more than DRAIN_FRAMES / 2 waiting presses take longer than that.
# Waiting presses are never thrown away to catch up; the game itself may ignore
# some that come too fast for it. Only when MAX_PENDING presses are already
# waiting is a new one refused.
HOLD_FRAMES = 8
GAP_FRAMES = 4
DRAIN_FRAMES = 60  # about one second
MAX_PENDING = 120  # at two frames per press, four seconds of backlog


class InputQueue:
    """Collects button presses from any thread; the emulator loop drains one key mask per frame."""

    def __init__(
        self,
        hold_frames: int = HOLD_FRAMES,
        gap_frames: int = GAP_FRAMES,
        drain_frames: int = DRAIN_FRAMES,
        max_pending: int = MAX_PENDING,
    ):
        if hold_frames < 1 or gap_frames < 1:
            raise ValueError("a press needs at least one frame held and one released")
        self._hold = hold_frames
        self._gap = gap_frames
        self._drain = drain_frames
        self._max_pending = max_pending
        self._pending: deque[tuple[Button, int]] = deque()  # (button, frame it must be over by)
        self._lock = threading.Lock()
        self._now = 0  # frames handed out so far
        self._current = Button(0)
        self._hold_left = 0
        self._gap_left = 0

    def press(self, button: Button) -> bool:
        """Queue one press. Returns False, and drops it, if max_pending presses are already waiting."""
        with self._lock:
            if len(self._pending) >= self._max_pending:
                return False
            self._pending.append((button, self._now + self._drain))
            return True

    def press_phone_key(self, key: str) -> Button | None:
        """Queue the button bound to a phone key; returns it, or None if the key is unbound."""
        button = PHONE_KEYS.get(key)
        if button is not None:
            self.press(button)
        return button

    def _start_next_press(self) -> None:
        self._current, _ = self._pending[0]
        # The longest this press may take so that it and everything behind it still finishes in time:
        # the press at position n has to be over by its deadline, after n presses of this length.
        frames = min((deadline - self._now) // position for position, (_, deadline) in enumerate(self._pending, 1))
        frames = max(2, min(frames, self._hold + self._gap))
        self._pending.popleft()
        # Split in the relaxed pace's proportion; this always leaves at least one frame for the release.
        self._hold_left = max(1, frames * self._hold // (self._hold + self._gap))
        self._gap_left = frames - self._hold_left

    def next_frame(self) -> Button:
        """Return the key mask to hold during the next emulated frame."""
        with self._lock:
            if not self._hold_left and not self._gap_left and self._pending:
                self._start_next_press()
            self._now += 1
            if self._hold_left:
                self._hold_left -= 1
                return self._current
            if self._gap_left:
                self._gap_left -= 1
            return Button(0)
