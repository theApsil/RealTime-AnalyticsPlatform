from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from generator.config import get_settings
from generator.generation.anomalies import AnomalyPolicy
from generator.generation.catalog import StationCatalog
from generator.generation.weather import BatchGenerator

SEED = 42


def main() -> None:
    settings = get_settings()
    catalog = StationCatalog(settings.generator.city_list)
    anomaly_policy = AnomalyPolicy(
        probability=settings.generator.anomaly_probability,
        strength=settings.generator.anomaly_strength,
        rng=random.Random(SEED),
    )
    batch = BatchGenerator(catalog, SEED, anomaly_policy)

    print("=" * 74)
    print("СЦЕНАРИЙ 1. Генерация в память (без БД)")
    print("=" * 74)
    print(f"Станций: {len(batch.stations)}")
    for st in batch.stations:
        print(f"  - {st.city:<14} id={st.station_id}")

    print("\nПоказания (8 записей, разные даты 2026 года):")
    print(f"  {'дата':<18}{'st':<4}{'temp':>7}{'hum%':>6}{'press':>8}{'wind':>6}  weather")
    base = datetime(2026, 1, 1, 12, tzinfo=UTC)  # время всегда 12:00
    for i in range(8):
        at = base + timedelta(days=46 * i)
        r = batch.generate_batch(at, size=1)[0]
        print(f"  {r.timestamp.strftime('%Y-%m-%d %H:%M'):<18}{r.station_id:<4}"
              f"{r.temperature_c:>7.2f}{r.humidity_pct:>6.1f}"
              f"{r.pressure_hpa:>8.1f}{r.wind_speed_ms:>6.2f}  "
              f"{r.weather_type.value}")

    print("\nВывод: данные сгенерированы, но никуда не записаны.")
    print("Переходим к СЦЕНАРИЮ 2 — запись в ClickHouse.")


if __name__ == "__main__":
    main()
