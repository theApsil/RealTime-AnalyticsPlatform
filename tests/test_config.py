"""Тесты конфигурации: значения по умолчанию, переопределение через env."""

from generator.config import ClickHouseSettings, GeneratorSettings


def test_generator_defaults() -> None:
    settings = GeneratorSettings(_env_file=None)
    assert settings.batch_size == 100
    assert settings.interval_seconds == 1.0
    assert settings.seed == 42
    assert settings.anomaly_probability == 0.02
    assert settings.anomaly_strength == 3.0
    assert settings.retry_max_attempts == 5
    assert settings.retry_base_delay_seconds == 0.5
    assert settings.retry_backoff_factor == 2.0
    assert "Vladivostok" in settings.city_list


def test_clickhouse_defaults() -> None:
    settings = ClickHouseSettings(_env_file=None)
    assert settings.host == "localhost"
    assert settings.port == 8123
    assert settings.database == "weather"
    assert settings.user == "default"


def test_env_overrides_with_prefixes(monkeypatch) -> None:
    monkeypatch.setenv("GENERATOR_BATCH_SIZE", "25")
    monkeypatch.setenv("GENERATOR_INTERVAL_SECONDS", "0.5")
    monkeypatch.setenv("GENERATOR_CITIES", "Moscow, Sochi")
    monkeypatch.setenv("CLICKHOUSE_HOST", "ch.internal")

    generator = GeneratorSettings(_env_file=None)
    clickhouse = ClickHouseSettings(_env_file=None)

    assert generator.batch_size == 25
    assert generator.interval_seconds == 0.5
    assert generator.city_list == ["Moscow", "Sochi"]
    assert clickhouse.host == "ch.internal"


def test_city_list_parses_comma_string() -> None:
    settings = GeneratorSettings(cities="A,B, C", _env_file=None)
    assert settings.city_list == ["A", "B", "C"]
