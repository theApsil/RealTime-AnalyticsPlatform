from __future__ import annotations

import argparse
import random
import sys
import threading
import time
from datetime import UTC, datetime

from _ch import DOCKER_CMD, ch_auth_ok, ch_is_ready

from generator.config import get_settings
from generator.generation.anomalies import AnomalyPolicy
from generator.generation.catalog import StationCatalog
from generator.generation.weather import BatchGenerator
from generator.repository.clickhouse import ClickHouseRepository
from generator.service.generator import build_service

SEED = 42


def wait_for_ch(timeout_seconds: float) -> None:
    settings = get_settings()
    ch = settings.clickhouse
    deadline = time.monotonic() + timeout_seconds
    print(f"Ожидаю готовности ClickHouse ({ch.host}:{ch.port}), "
          f"таймаут {timeout_seconds:.0f}с...")
    print(f"  (если ClickHouse ещё не запущен — запустите в другом терминале:\n"
          f"   {DOCKER_CMD})")
    while time.monotonic() < deadline:
        if ch_is_ready(ch):
            if not ch_auth_ok(ch):
                sys.exit("ClickHouse отвечает, но авторизация не прошла. "
                         "Проверьте CLICKHOUSE_USER / CLICKHOUSE_PASSWORD в .env "
                         "(например: CLICKHOUSE_PASSWORD=clickhouse).")
            print("  ClickHouse готов ✓ — генератор стартует.")
            return
        print("  ...ещё не готов, жду 1с")
        time.sleep(1)
    sys.exit(f"ClickHouse не поднялся за {timeout_seconds:.0f}с. Прерываюсь.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Генератор ждёт ClickHouse")
    parser.add_argument("--timeout", type=float, default=60.0, help="сек ожидания")
    args = parser.parse_args()

    print("=" * 74)
    print("СЦЕНАРИЙ 3. Генератор ждёт готовности ClickHouse")
    print("=" * 74)

    wait_for_ch(args.timeout)

    settings = get_settings()
    catalog = StationCatalog(settings.generator.city_list)
    anomaly_policy = AnomalyPolicy(
        probability=settings.generator.anomaly_probability,
        strength=settings.generator.anomaly_strength,
        rng=random.Random(SEED),
    )
    batch = BatchGenerator(catalog, SEED, anomaly_policy)
    repo = ClickHouseRepository(settings.clickhouse)
    service = build_service(
        settings=settings,
        batch_generator=batch,
        repository=repo,
        stop_event=threading.Event(),
    )

    print("\nЗапускаю генератор (схема + справочник + один батч)...")
    service.run_once()

    # Дописываем батчи на другие даты 2026 года (случайный час суток)
    print("Дописываю батчи на другие даты 2026 года...")
    for month in (2, 8):
        at = datetime(
            2026, month, 15,
            random.randint(0, 23), random.randint(0, 59),
            tzinfo=UTC,
        )
        repo.insert_readings(batch.generate_batch(at, settings.generator.batch_size))

    print("\nВывод: генератор стартовал только после готовности ClickHouse.")


if __name__ == "__main__":
    main()
