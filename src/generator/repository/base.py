"""Порт репозитория (интерфейс персистентности).

Определяет контракт, которому должны удовлетворять любые реализации хранилища
(ClickHouse, in-memory для тестов и т.д.). Сервис зависит только от этого
протокола — принцип инверсии зависимостей (DIP).
"""

from __future__ import annotations

from typing import Protocol

from generator.models import Station, WeatherReading


class Repository(Protocol):
    """Абстракция над хранилищем показаний и справочника станций."""

    def ensure_schema(self) -> None: ...

    def upsert_stations(self, stations: list[Station]) -> None: ...

    def insert_readings(self, readings: list[WeatherReading]) -> None: ...
