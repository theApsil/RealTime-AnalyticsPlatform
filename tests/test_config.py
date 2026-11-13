"""Тесты конфигурации: значения по умолчанию, переопределение через env."""

from datetime import UTC

from generator.config import ClickHouseSettings, GeneratorSettings


def test_generator_defaults() -> None:
    settings = GeneratorSettings(_env_file=None)
    assert settings.batch_size == 1000
    assert settings.backfill_start == "2025-01-01T00:00:00"
    assert settings.backfill_step_seconds == 60.0
    assert settings.realtime_step_seconds == 1.0
    assert settings.seed == 42
    assert settings.anomaly_probability == 0.02
    assert settings.anomaly_strength == 3.0
    assert settings.retry_max_attempts == 5
    assert settings.retry_base_delay_seconds == 0.5
    assert settings.retry_backoff_factor == 2.0
    assert "Vladivostok" in settings.city_list


def test_backfill_start_parsed_as_utc() -> None:
    settings = GeneratorSettings(backfill_start="2025-03-01T08:30:00", _env_file=None)
    assert settings.backfill_start_dt.year == 2025
    assert settings.backfill_start_dt.hour == 8
    assert settings.backfill_start_dt.tzinfo == UTC


def test_clickhouse_defaults() -> None:
    settings = ClickHouseSettings(_env_file=None)
    assert settings.host == "localhost"
    assert settings.port == 8123
    assert settings.database == "weather"
    assert settings.user == "default"


def test_env_overrides_with_prefixes(monkeypatch) -> None:
    monkeypatch.setenv("GENERATOR_BATCH_SIZE", "25")
    monkeypatch.setenv("GENERATOR_BACKFILL_STEP_SECONDS", "5.0")
    monkeypatch.setenv("GENERATOR_REALTIME_STEP_SECONDS", "2.0")
    monkeypatch.setenv("GENERATOR_CITIES", "Moscow, Sochi")
    monkeypatch.setenv("CLICKHOUSE_HOST", "ch.internal")

    generator = GeneratorSettings(_env_file=None)
    clickhouse = ClickHouseSettings(_env_file=None)

    assert generator.batch_size == 25
    assert generator.backfill_step_seconds == 5.0
    assert generator.realtime_step_seconds == 2.0
    assert generator.city_list == ["Moscow", "Sochi"]
    assert clickhouse.host == "ch.internal"


def test_city_list_parses_comma_string() -> None:
    settings = GeneratorSettings(cities="A,B, C", _env_file=None)
    assert settings.city_list == ["A", "B", "C"]
