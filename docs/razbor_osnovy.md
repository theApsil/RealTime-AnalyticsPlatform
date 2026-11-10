# Часть B. Подробный разбор файлов (основа проекта)

> models.py · config.py · seasonality.py · anomalies.py

---

## B1. models.py — доменные модели (ядро)

### Импорты

```python
from __future__ import annotations
import enum
from dataclasses import dataclass
from datetime import datetime
```

- `from __future__ import annotations` — **ленивые аннотации** (PEP 563): аннотации типов
  превращаются в строки и не вычисляются при импорте. Зачем: можно ссылаться на класс,
  объявленный ниже, и ускоряется импорт.
- `enum` — для перечисления `WeatherType`.
- `dataclasses` — для `@dataclass`.
- `datetime` — тип поля `timestamp`.

### WeatherType — перечисление категорий погоды

```python
class WeatherType(enum.StrEnum):
    CLEAR = "clear"
    CLOUDY = "cloudy"
    FOG = "fog"
    RAIN = "rain"
    SNOW = "snow"
    STORM = "storm"
```

**`StrEnum`** (Python 3.11+): значения перечисления **одновременно строки**.
`WeatherType.RAIN == "rain"` и сериализуется как `"rain"` — удобно для БД/JSON, но при
этом остаётся настоящим enum (защита от опечаток: `WeatherType.RAN` → ошибка).

### Station и WeatherReading — чистые модели

```python
@dataclass(frozen=True, slots=True)
class Station:
    station_id: int
    name: str
    city: str
    latitude: float
    longitude: float
    altitude: float
```

```python
@dataclass(frozen=True, slots=True)
class WeatherReading:
    station_id: int
    timestamp: datetime
    temperature_c: float
    humidity_pct: float
    pressure_hpa: float
    wind_speed_ms: float
    wind_direction_deg: float
    weather_type: WeatherType
    is_anomaly: bool
```

**Почему `@dataclass(frozen=True, slots=True)`:**
- `@dataclass` генерирует `__init__`, `__repr__`, `__eq__`.
- `frozen=True` — объект **неизменяем**: данные нельзя случайно изменить; объект безопасно
  шарить и использовать как ключ словаря.
- `slots=True` — нет `__dict__`, поля в компактном массиве: **меньше памяти** и быстрее
  доступ (показаний генерируются миллионы).

**Почему dataclass, а не Pydantic-модель:** домен должен быть «чистым» и не зависеть от
библиотек. Pydantic есть, но только в слое конфигурации.

> Итог: `models.py` — это ядро без единой внешней зависимости. На нём строятся все слои.

---

## B2. config.py — конфигурация

### Импорты и декораторы

```python
from dataclasses import dataclass
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
```

- `dataclasses` → `@dataclass` на `Settings` — контейнер двух объектов настроек.
- `functools.lru_cache` → **`@lru_cache`** на `get_settings()`: результат кэшируется по
  аргументам. Функция без аргументов → вычисляется **один раз**, дальше все возвращают тот
  же объект. Это **паттерн синглтон**: настройки читаются один раз за процесс.
- `pydantic.Field` → `Field(default=..., ge=..., le=...)` — дефолт + **валидация границ**.
- `pydantic_settings` → чтение из переменных окружения и `.env`.

### Классы настроек

```python
class ClickHouseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLICKHOUSE_", env_file=".env", ...)
    host: str = "localhost"
    port: int = 8123
    ...
```

```python
class GeneratorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GENERATOR_", env_file=".env", ...)
    batch_size: int = Field(default=100, ge=1)
    seed: int = 42
    anomaly_probability: float = Field(default=0.02, ge=0.0, le=1.0, ...)
    anomaly_strength: float = Field(default=3.0, ge=0.0)
    cities: str = "Vladivostok,Moscow,Kazan,Sochi,Irkutsk"
    retry_max_attempts: int = Field(default=5, ge=1)
    ...
```

**`model_config = SettingsConfigDict(...)`** — «паспорт загрузки» класса:
- `env_prefix="GENERATOR_"` — поле `batch_size` ищется как `GENERATOR_BATCH_SIZE`.
- `env_file=".env"` — источник значений.
- `env_file_encoding="utf-8"` — кодировка (важно для кириллицы).
- `extra="ignore"` — не падать на «чужих» переменных.
- `case_sensitive=False` — регистр env-переменных не важен.

Приоритет значений: **реальные переменные окружения → `.env` → дефолт в коде**.

### Свойство и синглтон

```python
@property
def city_list(self) -> list[str]:
    return [c.strip() for c in self.cities.split(",") if c.strip()]
```
**`@property`** — метод доступен как атрибут `settings.city_list` (без скобок). Превращает
строку `cities` в список на лету: `split(",")`, `strip()` убирает пробелы, `if c.strip()`
отбрасывает пустые элементы.

```python
@dataclass(frozen=True, slots=True)
class Settings:
    generator: GeneratorSettings
    clickhouse: ClickHouseSettings

@lru_cache
def get_settings() -> Settings:
    return Settings(generator=GeneratorSettings(), clickhouse=ClickHouseSettings())
```
`Settings` — неизменяемый агрегатор двух групп настроек. `@lru_cache` делает `get_settings()`
**синглтоном**: `.env`/env читаются и валидируются только один раз за процесс.

**Почему pydantic, а не `os.environ` руками:** `os.environ.get(...)` + проверки вручную —
это много кода и риск ошибок. pydantic даёт дефолты, валидацию, `.env` и один источник
правды «из коробки».

---

## B3. seasonality.py — сезонность (чистые функции)

### Импорты

```python
from __future__ import annotations
import math
from datetime import datetime
```

### diurnal_factor — суточный множитель

```python
def diurnal_factor(at: datetime) -> float:
    hour = at.hour + at.minute / 60.0 + at.second / 3600.0
    return math.cos(2.0 * math.pi * (hour - 15.0) / 24.0)
```

`hour` — перевод времени в **непрерывную долю суток в часах**: `15 + 30/60 + 45/3600 = 15.5125`.
Дроби нужны, чтобы при `14:59 → 15:00` не было «ступеньки» — кривая плавная.

`math.cos(2π * (hour − 15) / 24)` — косинус с **периодом 24 часа**:
- `/24` — за сутки проходит полный период `2π`;
- `(hour − 15)` — сдвиг фазы: при `hour = 15` аргумент `0`, `cos(0) = 1` (максимум в 15:00);
- минимум `−1` в 03:00.

| hour | фаза | cos |
|------|------|-----|
| 15:00 | 0 | **+1** (жарко) |
| 03:00 | −π | **−1** (холодно) |
| 09:00 / 21:00 | ±π/2 | 0 |

### annual_factor — годовой множитель

```python
def annual_factor(at: datetime) -> float:
    day_of_year = float(at.timetuple().tm_yday)
    return math.cos(2.0 * math.pi * (day_of_year - 196.0) / 365.25)
```

`at.timetuple().tm_yday` — **номер дня в году** (1..365/366). `float(...)` — для деления с
дробью.

`math.cos(2π * (day_of_year − 196) / 365.25)`:
- `/365.25` — период ~ год (средняя длина года с учётом високосных);
- `−196` — сдвиг: максимум `+1` в **середине июля** (~день 196), минимум `−1` в середине января.

**Почему чистые функции:** результат зависит только от `at` — нет `self`, нет состояния,
поэтому функции детерминированы и легко тестируются на фиксированных датах.

---

## B4. anomalies.py — аномалии

### Импорты

```python
from __future__ import annotations
import enum
import random
```

`__future__` здесь критично: `decide()` аннотирован через `AnomalyKind | None`, а
`AnomalyKind` объявлен **ниже** по файлу — без ленивых аннотаций был бы `NameError`.

### AnomalyKind — типы аномалий

```python
class AnomalyKind(enum.StrEnum):
    HEAT_WAVE = "heat_wave"
    COLD_SNAP = "cold_snap"
    PRESSURE_DROP = "pressure_drop"
    WIND_GUST = "wind_gust"
```

`StrEnum` — см. models.py. Значения — строки, удобно хранить в БД.

### AnomalyPolicy — политика аномалий

```python
class AnomalyPolicy:
    def __init__(self, probability: float, strength: float, rng: random.Random) -> None:
        self._probability = probability
        self._strength = strength
        self._rng = rng
```

**Инъекция `rng` извне**: генератор случайных чисел передаётся, а не создаётся внутри.
Зачем: `rng` сидирован (из `cli.py: random.Random(seed)`), поэтому решения детерминированы.

```python
@property
def strength(self) -> float:
    return self._strength
```
**`@property`** — read-only доступ к силе аномалии (можно читать, нельзя менять снаружи).

```python
def decide(self) -> AnomalyKind | None:
    if self._rng.random() >= self._probability:
        return None
    return self._rng.choice(list(AnomalyKind))
```

- `self._rng.random()` — следующее число из сидированного потока (диапазон `[0, 1)`).
- `>= probability` — в `100% − probability` случаев (например, 98%) вернуть `None`
  (аномалии нет).
- `self._rng.choice(list(AnomalyKind))` — равновероятно выбрать один из четырёх типов.

**Почему зависимость от рандома не ломает воспроизводимость:** `random()` не «тянет
случайность из воздуха», а детерминированно выдаёт числа по алгоритму от сида. Тот же сид
+ тот же порядок вызовов → тот же результат. Рандом — механизм детерминизма, а не помеха.

> Разделение ответственности: `decide()` решает **факт и тип** аномалии, а величина
> скачка вычисляется уже в `weather.py` через `_apply_*_anomaly`.