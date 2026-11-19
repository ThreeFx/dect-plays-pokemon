from dpp.input import Button, InputQueue


def test_press_is_held_then_released_before_the_next_press():
    queue = InputQueue(hold_frames=3, gap_frames=2)
    queue.press(Button.A)
    queue.press(Button.UP)
    frames = [queue.next_frame() for _ in range(10)]
    assert frames == [Button.A] * 3 + [0] * 2 + [Button.UP] * 3 + [0] * 2


def test_idle_queue_holds_nothing():
    queue = InputQueue()
    assert [queue.next_frame() for _ in range(5)] == [0] * 5


def test_phone_keys():
    queue = InputQueue(hold_frames=1, gap_frames=0)
    assert queue.press_phone_key("5") is Button.A
    assert queue.press_phone_key("3") is None
    assert queue.next_frame() == Button.A
    assert queue.next_frame() == 0


def test_full_queue_drops_the_oldest_press():
    queue = InputQueue(hold_frames=1, gap_frames=0, max_pending=2)
    for button in (Button.A, Button.B, Button.START):
        queue.press(button)
    assert [queue.next_frame() for _ in range(4)] == [Button.B, 0, Button.START, 0]
