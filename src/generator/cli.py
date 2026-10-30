"""CLI-точка входа и композиционный корень приложения.

Собирает все компоненты (настройки, справочник станций, генератор, репозиторий,
retry), настраивает логирование и обработку сигналов, запускает цикл.
"""

from __future__ import annotations

import argparse
import logging
import random
import signal
import threading
from collections.abc import Sequence

from generator.config import ClickHouseSettings, get_settings
from generator.generation.anomalies import AnomalyPolicy
from generator.generation.catalog import StationCatalog
from generator.generation.weather import BatchGenerator
from generator.repository.base import Repository
from generator.repository.clickhouse import ClickHouseRepository
from generator.repository.in_memory import InMemoryRepository
from generator.service.generator import build_service


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def install_signal_handlers(stop_event: threading.Event) -> None:
    """Переводит SIGINT/SIGTERM в установку stop_event (graceful shutdown).

    Внутри обработчика нельзя логировать или брать блокировки (это чревато
    гонками) — он лишь помечает событие остановки. Сообщение о полученном
    сигнале выводится уже в основном цикле сервиса.
    """

    def handler(signum: int, frame: object) -> None:
        del signum, frame  # не используем аргументы
        stop_event.set()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="weather-generator",
        description="Генератор потока данных погодной станции",
    )
    parser.add_argument(
        "--repository",
        choices=("in-memory", "clickhouse"),
        default="in-memory",
        help="Куда писать данные (по умолчанию in-memory — для запуска без БД)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Записать один батч и выйти (для быстрой проверки)",
    )
    return parser.parse_args(argv)


def _make_repository(kind: str, settings: ClickHouseSettings) -> Repository:
    if kind == "clickhouse":
        return ClickHouseRepository(settings)
    return InMemoryRepository()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    setup_logging(settings.generator.log_level)

    catalog = StationCatalog(settings.generator.city_list)
    anomaly_policy = AnomalyPolicy(
        probability=settings.generator.anomaly_probability,
        strength=settings.generator.anomaly_strength,
        rng=random.Random(settings.generator.seed),
    )
    batch_generator = BatchGenerator(catalog, settings.generator.seed, anomaly_policy)
    repository = _make_repository(args.repository, settings.clickhouse)

    stop_event = threading.Event()
    install_signal_handlers(stop_event)

    service = build_service(
        settings=settings,
        batch_generator=batch_generator,
        repository=repository,
        stop_event=stop_event,
    )

    if args.once:
        service.run_once()
    else:
        service.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
