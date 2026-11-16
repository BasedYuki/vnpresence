"""The easing behind the sliding pill: it must arrive, and arrive softly."""

from __future__ import annotations

from vnpresence import easing


def test_easing_starts_at_zero_and_lands_exactly_on_one():
    assert easing.ease_out_cubic(0) == 0
    assert easing.ease_out_cubic(1) == 1
    assert easing.ease_out_cubic(-3) == 0 and easing.ease_out_cubic(9) == 1


def test_it_is_fast_out_of_the_gate_and_soft_on_arrival():
    plan = easing.frames(240)
    steps = [b - a for a, b in zip([0.0, *plan], plan)]
    assert steps[0] > steps[-1] * 10  # big first step, tiny last one
    assert all(b >= a for a, b in zip(plan, plan[1:]))  # never goes backwards
    assert plan[-1] == 1.0  # ends exactly where it was going


def test_a_slide_is_about_a_quarter_of_a_second_at_sixty_frames():
    assert len(easing.frames(easing.SLIDE_MS)) == round(easing.SLIDE_MS / easing.FRAME_MS) == 15
    assert len(easing.frames(1)) == 1  # never zero frames


def test_lerp_goes_from_a_to_b():
    assert easing.lerp(10, 20, 0) == 10 and easing.lerp(10, 20, 1) == 20
    assert easing.lerp(10, 20, 0.5) == 15
