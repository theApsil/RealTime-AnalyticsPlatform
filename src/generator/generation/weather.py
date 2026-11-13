"""Генератор показаний одной станции.

``WeatherReadingGenerator`` — фасад над самплерами метрик: собирает все значения,
применяет аномалию (если выпала) и выбирает категорию погоды. Логика аномалий
инкапсулирована здесь же: самплеры об этом не знают.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from generator.models import Station, WeatherReading, WeatherType

from .anomalies import AnomalyKind, AnomalyPolicy
from .catalog import StationCatalog
from .metrics import (
    ClimateProfile,
    HumiditySampler,
    MetricSampler,
    PressureSampler,
    ReadingContext,
    TemperatureSampler,
    WindDirectionSampler,
    WindSpeedSampler,
)


class _WeatherTypePicker:
    """Детерминированная (от контекста и rng) эвристика выбора категории."""

    def pick(
        self,
        ctx: ReadingContext,
        humidity: float,
        pressure: float,
        wind: float,
        anomaly: AnomalyKind | None,
        rng: random.Random,
    ) -> WeatherType:
        if anomaly == AnomalyKind.WIND_GUST or wind > 20.0:
            return WeatherType.STORM
        if anomaly == AnomalyKind.PRESSURE_DROP or pressure < 1000.0:
            return WeatherType.RAIN

        # Температура ниже нуля при высокой влажности — снег вместо дождя.
        if humidity > 75.0 and rng.random() < 0.35:
            return WeatherType.SNOW if ctx.temperature_c <= 0.0 else WeatherType.RAIN
        if humidity > 80.0 and wind < 1.5:
            return WeatherType.FOG
        if humidity < 60.0:
            return WeatherType.CLEAR
        return WeatherType.CLOUDY


class WeatherReadingGenerator:
    """Генерирует реалистичное показание станции в заданный момент времени."""

    def __init__(
        self,
        station: Station,
        profile: ClimateProfile,
        anomaly_policy: AnomalyPolicy,
        rng: random.Random,
    ) -> None:
        self._station = station
        self._rng = rng
        self._anomaly_policy = anomaly_policy
        self._temp: MetricSampler = TemperatureSampler(profile)
        self._humidity: MetricSampler = HumiditySampler(profile)
        self._pressure: MetricSampler = PressureSampler(profile)
        self._wind: MetricSampler = WindSpeedSampler(profile)
        self._direction: MetricSampler = WindDirectionSampler(profile)
        self._weather_type = _WeatherTypePicker()

    @property
    def station(self) -> Station:
        return self._station

    def generate(self, at: datetime) -> WeatherReading:
        anomaly = self._anomaly_policy.decide()
        rng = self._rng

        ctx = ReadingContext(at=at, temperature_c=0.0)
        temperature = self._temp.sample(ctx, rng)
        temperature = self._apply_temperature_anomaly(temperature, anomaly)

        ctx = ReadingContext(at=at, temperature_c=temperature)
        humidity = self._humidity.sample(ctx, rng)
        pressure = self._apply_pressure_anomaly(self._pressure.sample(ctx, rng), anomaly)
        wind = self._apply_wind_anomaly(self._wind.sample(ctx, rng), anomaly)
        direction = self._direction.sample(ctx, rng)

        weather_type = self._weather_type.pick(
            ctx, humidity, pressure, wind, anomaly, rng
        )

        return WeatherReading(
            station_id=self._station.station_id,
            timestamp=at,
            temperature_c=temperature,
            humidity_pct=humidity,
            pressure_hpa=pressure,
            wind_speed_ms=wind,
            wind_direction_deg=direction,
            weather_type=weather_type,
            is_anomaly=anomaly is not None,
        )

    # --- Применение аномалий (внутренние хелперы) -----------------------------

    def _apply_temperature_anomaly(
        self, value: float, anomaly: AnomalyKind | None
    ) -> float:
        strength = self._anomaly_policy.strength
        if anomaly == AnomalyKind.HEAT_WAVE:
            return round(value + strength * self._rng.uniform(5.0, 8.0), 2)
        if anomaly == AnomalyKind.COLD_SNAP:
            return round(value - strength * self._rng.uniform(5.0, 8.0), 2)
        return value

    def _apply_pressure_anomaly(
        self, value: float, anomaly: AnomalyKind | None
    ) -> float:
        if anomaly == AnomalyKind.PRESSURE_DROP:
            drop = self._anomaly_policy.strength * self._rng.uniform(8.0, 25.0)
            return round(max(850.0, value - drop), 2)
        return value

    def _apply_wind_anomaly(self, value: float, anomaly: AnomalyKind | None) -> float:
        if anomaly == AnomalyKind.WIND_GUST:
            gust = value * self._anomaly_policy.strength * self._rng.uniform(2.0, 3.5)
            return round(min(60.0, gust), 2)
        return value


class BatchGenerator:
    """Производит пачку показаний по всем станциям за окно времени.

    Каждая запись батча получает свой момент времени: таймстемпы растут от
    ``at - (size-1)*step`` до ``at`` с шагом ``step_seconds``. Иначе все строки
    батча делили бы один таймстемп, сезонный/суточный фактор был бы одинаковым,
    и значения отличались бы только шумом (данные «прыгали» бы).
    Записи распределяются между станциями, чередуясь.
    """

    def __init__(
        self,
        catalog: StationCatalog,
        seed: int,
        anomaly_policy: AnomalyPolicy,
        step_seconds: float = 1.0,
    ) -> None:
        rng = random.Random(seed)
        self._step_seconds = float(step_seconds)
        self._per_station = [
            WeatherReadingGenerator(s, catalog.climate_for(s), anomaly_policy, rng)
            for s in catalog.stations()
        ]

    @property
    def stations(self) -> list[Station]:
        return [g.station for g in self._per_station]

    def generate_batch(self, at: datetime, size: int) -> list[WeatherReading]:
        if not self._per_station:
            return []
        step = self._step_seconds
        readings: list[WeatherReading] = []
        for index in range(size):
            generator = self._per_station[index % len(self._per_station)]
            # Батч покрывает окно, заканчивающееся в `at`: самые свежие в конце.
            ts = at - timedelta(seconds=(size - 1 - index) * step)
            readings.append(generator.generate(ts))
        return readings
