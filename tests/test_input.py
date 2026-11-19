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
    queue = InputQueue(hold_frames=1, gap_frames=1)
    assert queue.press_phone_key("5") is Button.A
    assert queue.press_phone_key("3") is None
    assert queue.next_frame() == Button.A
    assert queue.next_frame() == 0


def _presses(frames):
    """The buttons played, in order, with how many frames each was held."""
    played = []
    for previous, keys in zip([Button(0)] + frames, frames):
        if keys and keys != previous:
            played.append([keys, 1])
        elif keys:
            played[-1][1] += 1
    return played


ORDER = [Button.A, Button.B, Button.UP, Button.DOWN, Button.LEFT]


def test_a_burst_is_played_faster_so_it_is_over_within_the_drain_time():
    queue = InputQueue()  # 8 frames held, 4 released, drained within 60
    burst = [ORDER[i % 5] for i in range(15)]
    for button in burst:
        queue.press(button)
    frames = [queue.next_frame() for _ in range(60)]
    played = _presses(frames)
    assert [button for button, _ in played] == burst, "nothing is dropped or reordered"
    assert all(held >= 1 for _, held in played)
    assert queue.next_frame() == 0
    # Once the burst is through, a single press is played at the relaxed pace again.
    queue.press(Button.START)
    assert [queue.next_frame() for _ in range(13)] == [Button.START] * 8 + [0] * 5


def test_a_small_backlog_shortens_presses_only_as_much_as_needed():
    queue = InputQueue()
    for i in range(6):  # 6 presses in 60 frames: 10 frames each instead of 12
        queue.press(ORDER[i % 5])
    assert _presses([queue.next_frame() for _ in range(60)]) == [[ORDER[i % 5], 6] for i in range(6)]


def test_every_press_is_over_within_the_drain_time_of_arriving():
    queue = InputQueue()
    queue.press(Button.A)
    frames = [queue.next_frame() for _ in range(5)]  # A is being held at the relaxed pace
    for i in range(20):  # then 20 more arrive at once
        queue.press(ORDER[(i + 1) % 5])
    frames += [queue.next_frame() for _ in range(60)]
    assert len(_presses(frames)) == 21
    assert queue.next_frame() == 0


def test_a_huge_backlog_is_played_at_one_frame_held_one_released_and_none_is_lost():
    queue = InputQueue()
    burst = [Button.A] * 60 + [ORDER[i % 5] for i in range(60)]  # exactly what the queue holds
    assert all(queue.press(button) for button in burst)
    frames = [queue.next_frame() for _ in range(240)]
    assert frames == [keys for button in burst for keys in (button, 0)], "every press is followed by a release"
    assert queue.next_frame() == 0


def test_a_full_queue_refuses_new_presses_and_keeps_the_waiting_ones():
    queue = InputQueue(max_pending=2)
    assert [queue.press(button) for button in (Button.A, Button.B, Button.START)] == [True, True, False]
    assert queue.next_frame() == Button.A  # A is now playing, so there is room for one more
    assert queue.press(Button.SELECT) and not queue.press(Button.START)
    frames = [Button.A] + [queue.next_frame() for _ in range(80)]
    assert [button for button, _ in _presses(frames)] == [Button.A, Button.B, Button.SELECT]


def test_the_queue_holds_120_presses_by_default():
    queue = InputQueue()
    assert [queue.press(Button.A) for _ in range(121)] == [True] * 120 + [False]


def test_a_press_without_a_release_frame_is_not_allowed():
    import pytest

    with pytest.raises(ValueError):
        InputQueue(hold_frames=1, gap_frames=0)
