from __future__ import annotations

import random
import threading
from datetime import UTC, datetime

from _ch import DOCKER_CMD, ch_auth_ok, ch_client, ch_is_ready

from generator.config import get_settings
from generator.generation.anomalies import AnomalyPolicy
from generator.generation.catalog import StationCatalog
from generator.generation.weather import BatchGenerator
from generator.repository.clickhouse import ClickHouseRepository
from generator.service.generator import build_service

SEED = 42


def main() -> None:
    settings = get_settings()
    ch = settings.clickhouse

    print("=" * 74)
    print("СЦЕНАРИЙ 2. Запись в ClickHouse")
    print("=" * 74)
    print(f"Проверяю доступность ClickHouse ({ch.host}:{ch.port})...")

    if not ch_is_ready(ch):
        print("  ClickHouse НЕ отвечает.")
        print(f"  Запустите его, например:\n    {DOCKER_CMD}")
        print("  (затем повторите скрипт)")
        return

    if not ch_auth_ok(ch):
        print("  ClickHouse отвечает, но авторизация не прошла.")
        print("  Проверьте CLICKHOUSE_USER / CLICKHOUSE_PASSWORD в .env")
        print("  (например: CLICKHOUSE_PASSWORD=clickhouse)")
        return

    print("  ClickHouse доступен ✓")

    catalog = StationCatalog(settings.generator.city_list)
    anomaly_policy = AnomalyPolicy(
        probability=settings.generator.anomaly_probability,
        strength=settings.generator.anomaly_strength,
        rng=random.Random(SEED),
    )
    batch = BatchGenerator(catalog, SEED, anomaly_policy)
    repo = ClickHouseRepository(ch)
    service = build_service(
        settings=settings,
        batch_generator=batch,
        repository=repo,
        stop_event=threading.Event(),
    )

    print("\nЗапускаю генератор: схема + справочник + один батч...")
    service.run_once()

    # Дописываем ещё батчи на разных датах 2026 года (случайный час суток)
    print("Дописываю батчи на другие даты 2026 года...")
    for month in (1, 3, 6, 9):
        at = datetime(
            2026, month, 15,
            random.randint(0, 23), random.randint(0, 59),
            tzinfo=UTC,
        )
        repo.insert_readings(batch.generate_batch(at, settings.generator.batch_size))

    client = ch_client(ch)
    rows = client.query(
        f"SELECT timestamp, station_id, temperature_c, weather_type "
        f"FROM {ch.database}.readings ORDER BY timestamp LIMIT 8"
    ).result_rows
    print("\nНесколько записей из ClickHouse (видно разные даты 2026):")
    for row in rows:
        print("  ", row)

    print("\nВывод: данные записаны в ClickHouse. Переходим к СЦЕНАРИЮ 3.")


if __name__ == "__main__":
    main()
