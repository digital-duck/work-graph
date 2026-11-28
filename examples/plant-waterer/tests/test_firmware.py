# verifies: SPEC-001
# verifies: firmware
from src.firmware import should_water


def test_waters_after_ten_dry_minutes():
    assert should_water([10] * 10, runs_today=0)


def test_does_not_water_when_not_dry_long_enough_or_too_often():
    assert not should_water([10] * 9, runs_today=0)
    assert not should_water([10] * 10, runs_today=3)
