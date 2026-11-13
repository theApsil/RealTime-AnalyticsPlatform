"""Конфигурация генератора.

Настройки читаются из переменных окружения (префиксы ``GENERATOR_*`` для самого
генератора и ``CLICKHOUSE_*`` для подключения к БД) и из файла ``.env``.

Конфигурация — единственная точка правды обо всех «ручках» системы. Разделение
на два объекта (генератор / БД) держит независимые группы настроек отдельно.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ClickHouseSettings(BaseSettings):
    """Подключение к ClickHouse (префикс ``CLICKHOUSE_*``)."""

    model_config = SettingsConfigDict(
        env_prefix="CLICKHOUSE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    host: str = Field(default="localhost")
    port: int = Field(default=8123, ge=1, le=65535)
    database: str = Field(default="weather")
    user: str = Field(default="default")
    password: str = Field(default="")


class GeneratorSettings(BaseSettings):
    """Настройки генератора (префикс ``GENERATOR_*``)."""

    model_config = SettingsConfigDict(
        env_prefix="GENERATOR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Интенсивность и динамика ------------------------------------------
    batch_size: int = Field(default=100, ge=1, description="Записей в одном батче")
    interval_seconds: float = Field(
        default=1.0, ge=0.0, description="Пауза между батчами, секунды"
    )
    seed: int = Field(default=42, description="Seed для воспроизводимости генерации")
    anomaly_probability: float = Field(
        default=0.02, ge=0.0, le=1.0, description="Вероятность аномалии на запись"
    )
    anomaly_strength: float = Field(
        default=3.0, ge=0.0, description="Множитель силы аномалии"
    )

    # --- Справочник станций -------------------------------------------------
    cities: str = Field(
        default="Vladivostok,Moscow,Kazan,Sochi,Irkutsk",
        description="Города станций через запятую",
    )

    # --- Логирование ---------------------------------------------------------
    log_level: str = Field(default="INFO", description="Уровень логирования")

    # --- Retry: устойчивость к отказам БД --------------------------------------
    retry_max_attempts: int = Field(default=5, ge=1)
    retry_base_delay_seconds: float = Field(default=0.5, ge=0.0)
    retry_max_delay_seconds: float = Field(default=30.0, ge=0.0)
    retry_backoff_factor: float = Field(default=2.0, ge=1.0)

    # --- Control plane: рантайм-управление скоростью (0 = выключено) -------------
    control_host: str = Field(
        default="0.0.0.0", description="Адрес, на котором слушать control-endpoint"
    )
    control_port: int = Field(
        default=0, ge=0, le=65535, description="Порт control-endpoint (0 = не запускать)"
    )

    @property
    def city_list(self) -> list[str]:
        """Города как список (env хранит их строкой через запятую)."""
        return [c.strip() for c in self.cities.split(",") if c.strip()]


@dataclass(frozen=True, slots=True)
class Settings:
    """Единая точка доступа к конфигурации всего генератора."""

    generator: GeneratorSettings
    clickhouse: ClickHouseSettings


@lru_cache
def get_settings() -> Settings:
    """Возвращает синглтон настроек (кэшируется в рамках процесса)."""
    return Settings(generator=GeneratorSettings(), clickhouse=ClickHouseSettings())
