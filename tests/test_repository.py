"""Тесты in-memory репозитория: дедупликация справочника и накопление показаний."""

from datetime import UTC, datetime

from generator.models import Station, WeatherReading, WeatherType
from generator.repository.in_memory import InMemoryRepository


def _station(sid: int, city: str, altitude: float = 0.0) -> Station:
    return Station(sid, f"{city} Station", city, 0.0, 0.0, altitude)


def _reading(sid: int, at: datetime) -> WeatherReading:
    return WeatherReading(
        station_id=sid,
        timestamp=at,
        temperature_c=1.0,
        humidity_pct=50.0,
        pressure_hpa=1013.0,
        wind_speed_ms=2.0,
        wind_direction_deg=90.0,
        weather_type=WeatherType.CLEAR,
        is_anomaly=False,
    )


def test_upsert_stations_updates_by_id() -> None:
    repo = InMemoryRepository()
    repo.upsert_stations([_station(1, "Moscow"), _station(2, "Sochi")])
    repo.upsert_stations([_station(1, "Moscow", altitude=250.0)])
    assert [s.station_id for s in repo.stations] == [1, 2]
    assert repo.stations[0].altitude == 250.0


def test_insert_readings_appends_batches() -> None:
    repo = InMemoryRepository()
    at = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
    repo.insert_readings([_reading(1, at), _reading(2, at)])
    repo.insert_readings([_reading(1, at)])
    assert len(repo.readings) == 3
