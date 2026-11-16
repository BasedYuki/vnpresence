"""The timing of every movement in the window, away from Tk so it can be tested.

:func:`ease_out_cubic` is fast at the start and settles gently at the end, the
way a physical thing comes to rest; :func:`frames` is that curve sampled once
per frame at about 60 a second.
"""

from __future__ import annotations

#: One frame at ~60 fps.
FRAME_MS = 16
#: How long a slide takes.
SLIDE_MS = 240
#: How far a tab's page rises as it appears.
RISE_PX = 14


def ease_out_cubic(t: float) -> float:
    """0 -> 0, 1 -> 1, quick out of the gate and soft on arrival."""
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def frames(duration_ms: int = SLIDE_MS) -> list[float]:
    """The eased progress at each frame of a movement, ending exactly at 1."""
    count = max(round(duration_ms / FRAME_MS), 1)
    return [ease_out_cubic(i / count) for i in range(1, count + 1)]
