"""Тесты сезонных циклов как чистых функций времени."""

from datetime import UTC, datetime, timedelta

from generator.generation.seasonality import annual_factor, diurnal_factor


def _dt(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, 0, 0, tzinfo=UTC)


def test_diurnal_peak_afternoon_trough_night() -> None:
    assert diurnal_factor(_dt(2024, 6, 15, 15)) > 0.9  # ~15:00 — максимум
    assert diurnal_factor(_dt(2024, 6, 15, 3)) < -0.9  # ~03:00 — минимум


def test_diurnal_cycle_is_periodic() -> None:
    # Зависит только от времени суток — одинаково в любой день в один и тот же час.
    assert diurnal_factor(_dt(2024, 6, 15, 15)) == diurnal_factor(_dt(2024, 6, 16, 15))


def test_annual_warm_summer_cold_winter() -> None:
    assert annual_factor(_dt(2024, 7, 15)) > 0.9  # середина июля — жарко
    assert annual_factor(_dt(2024, 1, 15)) < -0.9  # середина января — холодно


def test_annual_factor_within_unit_interval() -> None:
    start = _dt(2024, 1, 1)
    for day in range(0, 366):
        at = start + timedelta(days=day)
        assert -1.0 <= annual_factor(at) <= 1.0
