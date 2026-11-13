"""Сервис генерации: бэкфилл исторических данных + realtime-дополнение.

Две фазы:
- ``backfill`` — заполняет окно от ``backfill_start`` (по умолчанию 2025-01-01)
  до текущего момента с шагом ``backfill_step_seconds``. Возобновляется с
  последнего таймстемпа в хранилище (без дублей).
- ``realtime`` — после достижения текущего времени генерирует 1 запись в секунду.

Сервис зависит только от абстракций (Repository, BatchGenerator, RetryPolicy),
не зная деталей конкретной БД.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from generator.config import Settings
from generator.control import GeneratorStatus
from generator.generation.weather import BatchGenerator
from generator.models import WeatherReading
from generator.repository.base import Repository
from generator.retry import RetryError, RetryPolicy

Clock = Callable[[], datetime]

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


class GeneratorService:
    """Основной цикл генератора: бэкфилл + realtime."""

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
        status: GeneratorStatus | None = None,
    ) -> None:
        self._settings = settings
        self._batch_generator = batch_generator
        self._repository = repository
        self._retry = retry
        self._stop_event = stop_event
        self._clock = clock
        self._sleep = sleep
        self._status = status

    # --- Публичный цикл ------------------------------------------------------

    def run(self) -> None:
        """Запускает генерацию до сигнала остановки."""
        logger.info("Инициализация схемы и справочника станций...")
        self._repository.ensure_schema()
        self._write_stations()
        logger.info("Станции записаны: %d.", len(self._batch_generator.stations))
        try:
            self._backfill()
            self._run_realtime()
        except RetryError as exc:
            logger.error("Запись данных не удалась: %s", exc)
        finally:
            logger.info("Генератор остановлен.")

    def run_once(self) -> None:
        """Инициализирует схему, пишет справочник и один батч показаний."""
        logger.info("Инициализация схемы и справочника станций...")
        self._repository.ensure_schema()
        self._write_stations()
        g = self._settings.generator
        start = g.backfill_start_dt
        last = self._repository.max_timestamp()
        ts = last + timedelta(seconds=g.realtime_step_seconds) if last else start
        batch = self._batch_generator.generate_sequence(ts, g.batch_size, g.backfill_step_seconds)
        self._store(batch)
        logger.info("Один батч записан, завершение.")

    # --- Фазы ----------------------------------------------------------------

    def _backfill(self) -> None:
        g = self._settings.generator
        start = g.backfill_start_dt
        step = g.backfill_step_seconds
        batch_size = g.batch_size
        now = self._clock()

        last = self._repository.max_timestamp()
        next_ts = last + timedelta(seconds=step) if last is not None and last >= start else start

        total_span = max((now - start).total_seconds(), 1.0)
        produced = 0
        while next_ts <= now and not self._stop_event.is_set():
            # Не заходим за `now`: последний батч обрезаем до оставшегося окна,
            # иначе появятся записи с будущими таймстемпами и realtime застрянет,
            # ожидая, пока реальное время догонит перескоченный `next_ts`.
            remaining = (now - next_ts).total_seconds()
            count = min(batch_size, int(remaining // step) + 1)
            batch = self._batch_generator.generate_sequence(next_ts, count, step)
            self._store(batch)
            produced += len(batch)
            next_ts = batch[-1].timestamp + timedelta(seconds=step)
            progress = min(100.0, (next_ts - start).total_seconds() / total_span * 100.0)
            self._update_status("backfill", next_ts, progress)
            if produced % (batch_size * 20) == 0:
                logger.info("Бэкфилл: до %s (%d строк, %.1f%%)", next_ts, produced, progress)

        logger.info("Бэкфилл завершён: %d строк, достигнуто %s", produced, next_ts)
        self._realtime_next = next_ts

    def _run_realtime(self) -> None:
        g = self._settings.generator
        step = g.realtime_step_seconds
        next_ts = getattr(self, "_realtime_next", None)
        if next_ts is None:
            last = self._repository.max_timestamp()
            next_ts = (last + timedelta(seconds=step)) if last else self._clock()

        while not self._stop_event.is_set():
            now = self._clock()
            if next_ts > now:
                # Ждём, пока таймстемп догонит реальное время.
                self._sleep(min(1.0, (next_ts - now).total_seconds()))
                continue
            batch = self._batch_generator.generate_sequence(next_ts, 1, step)
            self._store(batch)
            self._update_status("realtime", next_ts, 100.0)
            next_ts += timedelta(seconds=step)
            self._sleep(step)

    # --- Внутренние шаги ------------------------------------------------------

    def _write_stations(self) -> None:
        stations = self._batch_generator.stations
        self._retry.execute(lambda: self._repository.upsert_stations(stations))

    def _store(self, batch: list[WeatherReading]) -> None:
        self._retry.execute(lambda: self._repository.insert_readings(batch))

    def _update_status(self, mode: str, current_ts: datetime, progress: float) -> None:
        if self._status is not None:
            self._status.update(mode=mode, current_timestamp=current_ts, progress_pct=progress)


def build_service(
    *,
    settings: Settings,
    batch_generator: BatchGenerator,
    repository: Repository,
    stop_event: threading.Event,
    status: GeneratorStatus | None = None,
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
        status=status,
    )
