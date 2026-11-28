# implements: api
"""The cloud side: keep the readings the device sends."""

readings: list[tuple[str, int]] = []


def store(device_id: str, moisture: int) -> int:
    readings.append((device_id, moisture))
    return len(readings)
