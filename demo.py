#!/usr/bin/env python3
"""Живая демонстрация генератора данных для студентов.

Показывает: станции, суточный ход температуры, годовой ход,
аномалии и детерминизм по сиду.
"""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from generator.config import get_settings
from generator.generation.anomalies import AnomalyPolicy
from generator.generation.catalog import StationCatalog
from generator.generation.weather import BatchGenerator, WeatherReadingGenerator
from generator.models import Station

SEED = 42


def make_policy(settings, seed: int) -> AnomalyPolicy:
    return AnomalyPolicy(
        probability=settings.generator.anomaly_probability,
        strength=settings.generator.anomaly_strength,
        rng=random.Random(seed),
    )


def make_batch(catalog: StationCatalog, seed: int) -> BatchGenerator:
    return BatchGenerator(catalog, seed, make_policy(get_settings(), seed))


def main() -> None:
    settings = get_settings()
    catalog = StationCatalog(settings.generator.city_list)
    batch = make_batch(catalog, SEED)

    print("=" * 72)
    print("1. СТАНЦИИ И КЛИМАТ")
    print("=" * 72)
    for st in batch.stations:
        prof = catalog.climate_for(st)
        print(f"  {st.city:<14} средняя год. t={prof.mean_annual_temp_c:>5.1f}°C  "
              f"год. амплитуда={prof.annual_temp_amplitude_c:>5.1f}  "
              f"суточная ампл.={prof.daily_temp_amplitude_c:>4.1f}")

    moscow: Station = next(s for s in batch.stations if s.city == "Moscow")
    gen = WeatherReadingGenerator(
        moscow, catalog.climate_for(moscow), make_policy(settings, SEED),
        random.Random(SEED),
    )

    print()
    print("=" * 72)
    print("2. СУТОЧНЫЙ ХОД ТЕМПЕРАТУРЫ (Москва, каждый час)")
    print("   Пик ~15:00, минимум ~03:00")
    print("=" * 72)
    base = datetime(2026, 6, 21, tzinfo=UTC)  # летнее солнцестояние
    print("  час | температура")
    print("  ----|-------------")
    for h in range(24):
        t = gen.generate(base + timedelta(hours=h))
        bar = "#" * max(0, int(t.temperature_c * 2))
        print(f"  {h:>3} | {t.temperature_c:>7.2f}  {bar}")

    print()
    print("=" * 72)
    print("3. ГОДОВОЙ ХОД (Москва): середина июля vs середина января")
    print("=" * 72)
    july = gen.generate(datetime(2026, 7, 15, 15, tzinfo=UTC))
    jan = gen.generate(datetime(2026, 1, 15, 15, tzinfo=UTC))
    print(f"  15 июля  15:00  t = {july.temperature_c:>6.2f}°C")
    print(f"  15 января 15:00 t = {jan.temperature_c:>6.2f}°C")

    print()
    print("=" * 72)
    print("4. АНОМАЛИИ: прогоняем много записей, ищем is_anomaly=True")
    print("=" * 72)
    anomalies_found = 0
    for i in range(5000):
        r = gen.generate(base + timedelta(minutes=i))
        if r.is_anomaly:
            anomalies_found += 1
            if anomalies_found <= 5:
                print(f"  [{r.timestamp:%m-%d %H:%M}] t={r.temperature_c:>6.2f}  "
                      f"wind={r.wind_speed_ms:>5.2f}  press={r.pressure_hpa:>7.1f}")
    print(f"  Всего аномалий на 5000 записей: {anomalies_found}")

    print()
    print("=" * 72)
    print("5. ДЕТЕРМИНИЗМ: два запуска с одним сидом дают одинаковые данные")
    print("=" * 72)
    gen_a = make_batch(catalog, SEED)
    gen_b = make_batch(catalog, SEED)
    at = datetime(2026, 6, 21, 12, tzinfo=UTC)
    ra = gen_a.generate_batch(at, 20)
    rb = gen_b.generate_batch(at, 20)
    equal = [x.temperature_c for x in ra] == [x.temperature_c for x in rb]
    print(f"  Одинаковы ли батчи (seed=42): {equal}")
    print(f"  Первые 3 температуры: {[x.temperature_c for x in ra[:3]]}")


if __name__ == "__main__":
    main()
