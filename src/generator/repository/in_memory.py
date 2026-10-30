"""In-memory реализация репозитория.

Нужна для юнит-тестов и локального запуска без ClickHouse: показывает
интерфейс хранилища, не требуя внешней БД.
"""

from __future__ import annotations

from generator.models import Station, WeatherReading


class InMemoryRepository:
    """Хранит данные в списках в оперативной памяти."""

    def __init__(self) -> None:
        self.stations: list[Station] = []
        self.readings: list[WeatherReading] = []

    def ensure_schema(self) -> None:
        """In-memory хранилище не требует инициализации схемы."""

    def upsert_stations(self, stations: list[Station]) -> None:
        by_id = {s.station_id: s for s in self.stations}
        for station in stations:
            by_id[station.station_id] = station
        self.stations = sorted(by_id.values(), key=lambda s: s.station_id)

    def insert_readings(self, readings: list[WeatherReading]) -> None:
        self.readings.extend(readings)
