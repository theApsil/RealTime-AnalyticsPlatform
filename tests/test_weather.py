"""Тесты генерации показаний и батчей."""

import random
from datetime import UTC, datetime

from generator.generation.anomalies import AnomalyPolicy
from generator.generation.catalog import StationCatalog
from generator.generation.weather import BatchGenerator
from generator.models import WeatherType

CATALOG = StationCatalog(["Moscow", "Sochi"])
_AT = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)


def _policy(probability: float = 0.0, seed: int = 42) -> AnomalyPolicy:
    return AnomalyPolicy(probability, strength=3.0, rng=random.Random(seed))


def test_batch_covers_all_stations() -> None:
    generator = BatchGenerator(CATALOG, seed=1, anomaly_policy=_policy())
    batch = generator.generate_batch(_AT, size=10)
    assert len(batch) == 10
    assert {r.station_id for r in batch} == {0, 1}


def test_generation_is_reproducible_with_seed() -> None:
    first = BatchGenerator(CATALOG, seed=7, anomaly_policy=_policy(seed=7))
    second = BatchGenerator(CATALOG, seed=7, anomaly_policy=_policy(seed=7))
    b1 = first.generate_batch(_AT, 5)
    b2 = second.generate_batch(_AT, 5)
    assert [(r.temperature_c, r.humidity_pct) for r in b1] == [
        (r.temperature_c, r.humidity_pct) for r in b2
    ]


def test_every_reading_is_anomaly_when_probability_is_one() -> None:
    generator = BatchGenerator(CATALOG, seed=2, anomaly_policy=_policy(probability=1.0, seed=2))
    batch = generator.generate_batch(_AT, 20)
    assert all(r.is_anomaly for r in batch)


def test_no_anomalies_when_probability_is_zero() -> None:
    generator = BatchGenerator(CATALOG, seed=3, anomaly_policy=_policy(probability=0.0, seed=3))
    batch = generator.generate_batch(_AT, 20)
    assert all(not r.is_anomaly for r in batch)


def test_weather_type_is_valid_enum() -> None:
    generator = BatchGenerator(CATALOG, seed=4, anomaly_policy=_policy())
    batch = generator.generate_batch(_AT, 50)
    assert all(isinstance(r.weather_type, WeatherType) for r in batch)


def test_empty_catalog_yields_empty_batch() -> None:
    generator = BatchGenerator(StationCatalog([]), seed=1, anomaly_policy=_policy())
    assert generator.generate_batch(_AT, 10) == []
