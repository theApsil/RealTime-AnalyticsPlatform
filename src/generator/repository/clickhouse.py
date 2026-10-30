"""ClickHouse-реализация репозитория.

Батчевая вставка показаний одним запросом ``INSERT`` (а не по строке) и
идемпотентная инициализация таблиц при первом запуске. Соединение создаётся
лениво и переиспользуется.

Примечание: материализованные представления и агрегирующие таблицы разбираются
в отдельном воркшопе по ClickHouse, здесь — только таблицы-источники.
"""

from __future__ import annotations

from typing import Any

import clickhouse_connect

from generator.config import ClickHouseSettings
from generator.models import Station, WeatherReading

from .base import Repository

_STATIONS_COLUMNS = [
    "station_id",
    "name",
    "city",
    "latitude",
    "longitude",
    "altitude",
]

_READINGS_COLUMNS = [
    "station_id",
    "timestamp",
    "temperature_c",
    "humidity_pct",
    "pressure_hpa",
    "wind_speed_ms",
    "wind_direction_deg",
    "weather_type",
    "is_anomaly",
]


class ClickHouseRepository(Repository):
    """Пишет данные в ClickHouse через HTTP-интерфейс (клиент clickhouse-connect)."""

    def __init__(self, settings: ClickHouseSettings) -> None:
        self._settings = settings
        self._client: Any | None = None

    def _conn(self) -> Any:
        if self._client is None:
            self._client = clickhouse_connect.get_client(
                host=self._settings.host,
                port=self._settings.port,
                username=self._settings.user,
                password=self._settings.password,
                database=self._settings.database,
            )
        return self._client

    def ensure_schema(self) -> None:
        """Создаёт таблицы, если их ещё нет (идемпотентно)."""
        db = self._settings.database
        self._conn().command(f"CREATE DATABASE IF NOT EXISTS {db}")
        self._conn().command(
            f"""
            CREATE TABLE IF NOT EXISTS {db}.stations (
                station_id UInt32,
                name String,
                city String,
                latitude Float64,
                longitude Float64,
                altitude Float64
            ) ENGINE = MergeTree
            ORDER BY station_id
            """
        )
        self._conn().command(
            f"""
            CREATE TABLE IF NOT EXISTS {db}.readings (
                station_id UInt32,
                timestamp DateTime64(3, 'UTC'),
                temperature_c Float64,
                humidity_pct Float64,
                pressure_hpa Float64,
                wind_speed_ms Float64,
                wind_direction_deg Float64,
                weather_type String,
                is_anomaly UInt8
            ) ENGINE = MergeTree
            PARTITION BY toYYYYMM(timestamp)
            ORDER BY (station_id, timestamp)
            """
        )

    def upsert_stations(self, stations: list[Station]) -> None:
        rows = [
            (
                s.station_id,
                s.name,
                s.city,
                s.latitude,
                s.longitude,
                s.altitude,
            )
            for s in stations
        ]
        if rows:
            self._conn().insert(
                f"{self._settings.database}.stations",
                rows,
                column_names=_STATIONS_COLUMNS,
            )

    def insert_readings(self, readings: list[WeatherReading]) -> None:
        rows = [
            (
                r.station_id,
                r.timestamp,
                r.temperature_c,
                r.humidity_pct,
                r.pressure_hpa,
                r.wind_speed_ms,
                r.wind_direction_deg,
                r.weather_type.value,
                int(r.is_anomaly),
            )
            for r in readings
        ]
        if rows:
            self._conn().insert(
                f"{self._settings.database}.readings",
                rows,
                column_names=_READINGS_COLUMNS,
            )
