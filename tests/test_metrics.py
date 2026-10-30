"""Тесты самплеров метрик: сезонность, корреляции, диапазоны значений."""

import random
from datetime import UTC, datetime

from generator.generation.metrics import (
    ClimateProfile,
    HumiditySampler,
    PressureSampler,
    ReadingContext,
    TemperatureSampler,
    WindSpeedSampler,
)

PROFILE = ClimateProfile(
    mean_annual_temp_c=10.0,
    annual_temp_amplitude_c=20.0,
    daily_temp_amplitude_c=8.0,
    humidity_base_pct=70.0,
)


def _ctx(hour: int, temperature: float) -> ReadingContext:
    at = datetime(2024, 6, 15, hour, 0, 0, tzinfo=UTC)
    return ReadingContext(at=at, temperature_c=temperature)


def test_temperature_winter_night_colder_than_summer_day() -> None:
    rng = random.Random(0)
    sampler = TemperatureSampler(PROFILE)
    winter = sampler.sample(
        ReadingContext(datetime(2024, 1, 15, 3, tzinfo=UTC), 0.0), rng
    )
    summer = sampler.sample(_ctx(15, 0.0), rng)
    assert winter < summer


def test_humidity_inversely_correlates_with_temperature() -> None:
    rng = random.Random(1)
    sampler = HumiditySampler(PROFILE)
    cold = sampler.sample(_ctx(12, 0.0), rng)
    hot = sampler.sample(_ctx(12, 20.0), rng)
    assert cold > hot
    assert 5.0 <= hot <= 100.0


def test_pressure_stays_near_base() -> None:
    rng = random.Random(2)
    sampler = PressureSampler(PROFILE)
    value = sampler.sample(_ctx(12, 10.0), rng)
    assert 850.0 <= value <= 1100.0
    assert abs(value - PROFILE.pressure_base_hpa) < 30.0


def test_wind_speed_is_non_negative() -> None:
    rng = random.Random(3)
    sampler = WindSpeedSampler(PROFILE)
    for _ in range(50):
        value = sampler.sample(_ctx(12, 10.0), rng)
        assert value >= 0.0
