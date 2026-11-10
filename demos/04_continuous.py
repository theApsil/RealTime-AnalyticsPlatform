from __future__ import annotations

import argparse
import logging
import random
import threading

from generator.cli import install_signal_handlers
from generator.config import get_settings
from generator.generation.anomalies import AnomalyPolicy
from generator.generation.catalog import StationCatalog
from generator.generation.weather import BatchGenerator
from generator.repository.clickhouse import ClickHouseRepository
from generator.repository.in_memory import InMemoryRepository
from generator.service.generator import build_service

SEED = 42


def main() -> None:
    parser = argparse.ArgumentParser(description="Непрерывная генерация")
    parser.add_argument(
        "--repository",
        choices=("in-memory", "clickhouse"),
        default="in-memory",
        help="куда писать (по умолчанию in-memory)",
    )
    args = parser.parse_args()

    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.generator.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    catalog = StationCatalog(settings.generator.city_list)
    anomaly_policy = AnomalyPolicy(
        probability=settings.generator.anomaly_probability,
        strength=settings.generator.anomaly_strength,
        rng=random.Random(SEED),
    )
    batch = BatchGenerator(catalog, SEED, anomaly_policy)
    repo = (
        InMemoryRepository()
        if args.repository == "in-memory"
        else ClickHouseRepository(settings.clickhouse)
    )

    stop_event = threading.Event()
    install_signal_handlers(stop_event)

    service = build_service(
        settings=settings,
        batch_generator=batch,
        repository=repo,
        stop_event=stop_event,
    )

    print("=" * 74)
    print("СЦЕНАРИЙ 4. Непрерывная генерация + graceful shutdown")
    print(f"  репозиторий: {args.repository} · батч={settings.generator.batch_size} "
          f"· интервал={settings.generator.interval_seconds}s")
    print("  Нажмите Ctrl+C для остановки.")
    print("=" * 74)

    service.run()
    print("\nВывод: генератор остановлен корректно (graceful shutdown).")


if __name__ == "__main__":
    main()
