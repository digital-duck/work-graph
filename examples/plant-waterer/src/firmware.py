# implements: firmware
"""Decide when to water: the soil must stay dry for a while, and the pump may run only a few times a day."""

DRY_BELOW = 30        # percent
DRY_MINUTES = 10
MAX_RUNS_PER_DAY = 3


def should_water(readings: list[int], runs_today: int) -> bool:
    """`readings` is one soil-moisture percentage per minute, newest last."""
    recent = readings[-DRY_MINUTES:]
    return len(recent) == DRY_MINUTES and all(r < DRY_BELOW for r in recent) and runs_today < MAX_RUNS_PER_DAY
