"""Тесты сервиса генерации: бэкфилл, realtime, graceful shutdown, обработка отказов БД."""

import random
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from generator.config import ClickHouseSettings, GeneratorSettings, Settings
from generator.generation.anomalies import AnomalyPolicy
from generator.generation.catalog import StationCatalog
from generator.generation.weather import BatchGenerator
from generator.repository.in_memory import InMemoryRepository
from generator.retry import RetryError, RetryPolicy
from generator.service.generator import GeneratorService

_AT = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
_AT_ISO = _AT.isoformat()  # "2024-06-15T12:00:00+00:00"


class AdvancingClock:
    """Монотонно растущий таймстемп для теста realtime-фазы."""

    def __init__(self, start: datetime) -> None:
        self._t = start

    def __call__(self) -> datetime:
        cur = self._t
        self._t += timedelta(seconds=1)
        return cur


def _make_settings(
    batch_size: int = 10,
    cities: tuple[str, ...] = ("Moscow", "Sochi"),
    backfill_start: str = "2024-01-01T00:00:00",
    backfill_step_seconds: float = 1.0,
) -> Settings:
    generator = GeneratorSettings(
        _env_file=None,
        batch_size=batch_size,
        backfill_start=backfill_start,
        backfill_step_seconds=backfill_step_seconds,
        realtime_step_seconds=1.0,
        cities=",".join(cities),
        seed=0,
        anomaly_probability=0.0,
    )
    return Settings(generator=generator, clickhouse=ClickHouseSettings(_env_file=None))


def _make_service(
    settings: Settings,
    repo: InMemoryRepository,
    stop_event: threading.Event,
    clock=None,
) -> GeneratorService:
    catalog = StationCatalog(settings.generator.city_list)
    policy = AnomalyPolicy(
        probability=settings.generator.anomaly_probability,
        strength=settings.generator.anomaly_strength,
        rng=random.Random(settings.generator.seed),
    )
    batch_generator = BatchGenerator(catalog, settings.generator.seed, policy)
    retry = RetryPolicy(max_attempts=3, base_delay=0.0, max_delay=0.0)
    return GeneratorService(
        settings=settings,
        batch_generator=batch_generator,
        repository=repo,
        retry=retry,
        stop_event=stop_event,
        clock=clock or (lambda: _AT),
        sleep=lambda _: None,
    )


def test_run_once_writes_stations_and_one_batch() -> None:
    settings = _make_settings(batch_size=10)
    repo = InMemoryRepository()
    _make_service(settings, repo, threading.Event()).run_once()
    assert len(repo.stations) == 2
    assert len(repo.readings) == 10


def test_run_with_already_set_stop_writes_no_readings() -> None:
    settings = _make_settings(batch_size=5)
    repo = InMemoryRepository()
    stop = threading.Event()
    stop.set()
    _make_service(settings, repo, stop).run()
    assert len(repo.stations) == 2
    assert len(repo.readings) == 0


def test_run_keeps_generating_until_signal() -> None:
    settings = _make_settings(batch_size=5, backfill_start=_AT_ISO)
    repo = InMemoryRepository()
    stop = threading.Event()
    service = _make_service(settings, repo, stop, clock=AdvancingClock(_AT))

    thread = threading.Thread(target=service.run)
    thread.start()
    time.sleep(0.05)
    stop.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert len(repo.stations) == 2
    assert len(repo.readings) >= 5


def test_backfill_resumes_from_last_timestamp_without_duplicates() -> None:
    settings = _make_settings(batch_size=5, backfill_start=_AT_ISO)
    repo = InMemoryRepository()
    service = _make_service(settings, repo, threading.Event())
    # Первый прогон: заполняет 1 батч с 12:00:00.
    service.run_once()
    first = sorted(r.timestamp for r in repo.readings)
    assert len(repo.readings) == 5
    # Второй прогон: должен продолжить С ПОСЛЕДНЕГО таймстемпа, не дублируя.
    service.run_once()
    all_ts = sorted(r.timestamp for r in repo.readings)
    assert len(repo.readings) == 10  # ровно 5 новых, без дублей
    assert all_ts[:5] == first


def test_backfill_never_overshoots_now() -> None:
    """Бэкфилл не создаёт записей с будущими таймстемпами (после `now`)."""
    now = datetime(2025, 1, 10, 12, 0, 0, tzinfo=UTC)  # ~9.5 суток после старта
    settings = _make_settings(
        batch_size=5, backfill_start="2025-01-01T00:00:00", backfill_step_seconds=60.0
    )
    repo = InMemoryRepository()
    service = _make_service(settings, repo, threading.Event(), clock=lambda: now)

    service._backfill()

    ts = sorted(r.timestamp for r in repo.readings)
    assert ts == sorted(set(ts))  # без дублей
    assert all(t <= now for t in ts)  # ничего в будущем
    expected = int((now - ts[0]).total_seconds() // 60) + 1
    assert len(repo.readings) == expected


def test_run_once_propagates_retry_error_when_db_unavailable() -> None:
    settings = _make_settings(batch_size=5)

    class FailingRepository(InMemoryRepository):
        def ensure_schema(self) -> None:
            pass

        def upsert_stations(self, stations) -> None:  # type: ignore[no-untyped-def]
            raise ConnectionError("clickhouse is down")

    repo = FailingRepository()
    with pytest.raises(RetryError):
        _make_service(settings, repo, threading.Event()).run_once()
