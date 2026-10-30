"""Сервис генерации: оркестрирует цикл «произвести батч → записать в БД».

Сервис ничего не знает о конкретной БД и о том, как именно генерируются данные
— он зависит от абстракций (порт ``Repository``, ``BatchGenerator``, ``RetryPolicy``).
Это даёт возможность подменять реализации в тестах и при запуске без ClickHouse.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from generator.config import Settings
from generator.generation.weather import BatchGenerator
from generator.repository.base import Repository
from generator.retry import RetryError, RetryPolicy

Clock = Callable[[], datetime]

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


class GeneratorService:
    """Основной цикл генератора данных."""

    def __init__(
        self,
        *,
        settings: Settings,
        batch_generator: BatchGenerator,
        repository: Repository,
        retry: RetryPolicy,
        stop_event: threading.Event,
        clock: Clock = utc_now,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._batch_generator = batch_generator
        self._repository = repository
        self._retry = retry
        self._stop_event = stop_event
        self._clock = clock
        self._sleep = sleep
        self._last_batch_started = 0.0

    def run(self) -> None:
        """Запускает цикл генерации до сигнала остановки."""
        logger.info("Инициализация схемы и справочника станций...")
        self._repository.ensure_schema()
        self._write_stations()
        logger.info(
            "Станции записаны: %d. Запуск генерации (батч %d записей, интервал %.2fs)",
            len(self._batch_generator.stations),
            self._settings.generator.batch_size,
            self._settings.generator.interval_seconds,
        )

        try:
            while not self._stop_event.is_set():
                self._produce_and_store_batch()
        except RetryError as exc:
            logger.error("Запись данных не удалась: %s", exc)
        finally:
            logger.info("Генератор остановлен.")

    def run_once(self) -> None:
        """Инициализирует схему, пишет справочник и один батч показаний."""
        logger.info("Инициализация схемы и справочника станций...")
        self._repository.ensure_schema()
        self._write_stations()
        self._produce_and_store_batch()
        logger.info("Один батч записан, завершение.")

    # --- Внутренние шаги ------------------------------------------------------

    def _write_stations(self) -> None:
        stations = self._batch_generator.stations
        self._retry.execute(lambda: self._repository.upsert_stations(stations))

    def _produce_and_store_batch(self) -> None:
        started = time.monotonic()
        batch = self._batch_generator.generate_batch(
            self._clock(), self._settings.generator.batch_size
        )
        self._retry.execute(lambda: self._repository.insert_readings(batch))
        anomalies = sum(1 for r in batch if r.is_anomaly)
        logger.debug(
            "Записано %d показаний (аномалий: %d)", len(batch), anomalies
        )
        self._sleep(self._remaining(started))

    def _remaining(self, started: float) -> float:
        elapsed = time.monotonic() - started
        return max(0.0, self._settings.generator.interval_seconds - elapsed)


def build_service(
    *,
    settings: Settings,
    batch_generator: BatchGenerator,
    repository: Repository,
    stop_event: threading.Event,
) -> GeneratorService:
    """Композиционный корень: собирает сервис с политикой retry из настроек."""
    retry = RetryPolicy(
        max_attempts=settings.generator.retry_max_attempts,
        base_delay=settings.generator.retry_base_delay_seconds,
        max_delay=settings.generator.retry_max_delay_seconds,
        backoff_factor=settings.generator.retry_backoff_factor,
    )
    return GeneratorService(
        settings=settings,
        batch_generator=batch_generator,
        repository=repository,
        retry=retry,
        stop_event=stop_event,
    )
