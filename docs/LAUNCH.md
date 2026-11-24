# 🚀 Запуск платформы RealTime-AnalyticsPlatform

Полная платформа (генератор → ClickHouse → Superset → UI → Jupyter) поднимается
одним `docker-compose`. Это пошаговая инструкция с нуля.

## 1. Требования

- **Docker** + **Docker Compose** (используется standalone-бинарник `docker-compose`).
- **Корпоративная сеть** — образы тянутся через прокси-реестр Artifactory
  (`docker-proxy.artifactory.tcsbank.ru`), т.к. `docker.io` внутри контура заблокирован.

> Вне корпоративной сети замените в `superset/Dockerfile`, `jupyter/Dockerfile` и
> `docker-compose.yml` прокси-префикс `docker-proxy.artifactory.tcsbank.ru/` на
> официальные образы (`apache/superset:latest`, `jupyter/scipy-notebook:latest`,
> `clickhouse/clickhouse-server`).

## 2. Скачивание и сборка образов

```bash
cd <корень проекта>

# скачать внешние образы (ClickHouse и др.) через прокси-реестр
docker-compose pull

# собрать локальные образы (generator, superset, ui, jupyter)
docker-compose build
```

> `build` соберёт:
> - `generator` — Python-генератор потока данных;
> - `superset` — BI с драйвером ClickHouse;
> - `ui` — веб-дашборд платформы;
> - `jupyter` — Jupyter с pandas/matplotlib и драйвером ClickHouse.
>
> Образ `jupyter` тяжёлый (~5 ГБ) — первая сборка долгая.

## 3. Старт всех сервисов

```bash
docker-compose up -d
docker-compose ps
```

Дождитесь `healthy` для **clickhouse** и **superset**. При первом старте Superset
автоматически инициализируется (см. п.5).

## 4. Сервисы и точки входа

| Сервис | URL / порт | Логин / примечание |
|--------|-----------|--------------------|
| **ClickHouse** | `localhost:8123` (HTTP), `9000` (TCP) | user `default`, пароль `clickhouse`, БД `weather` |
| **generator** | `localhost:9100` | control-endpoint (GET `/rate`, POST `/stop`) |
| **Superset** | `localhost:8088` | `admin` / `admin` |
| **UI** | `localhost:8000` | веб-дашборд платформы (статус/логи/данные) |
| **Jupyter** | `localhost:8888` | токен входа `weather` |

## 5. Superset: первый запуск

Entrypoint контейнера `superset` при первом старте сам выполняет:
`db upgrade` → создание администратора → `superset init` (права) → подключение к
ClickHouse (база **`ClickHouse`**).

- Открыть `http://localhost:8088` и войти под `admin` / `admin`.

## 6. Дашборд в Superset

Чарты и дашборд создаются скриптами из `superset/` (идемпотентно — повторный запуск
безопасен). Выполнить один раз:

```bash
docker cp superset/provision_dashboard.py superset:/app/provision_dashboard.py
docker exec superset python3 /app/provision_dashboard.py   # датасеты + 13 чартов

docker cp superset/build_dashboard.py superset:/app/build_dashboard.py
docker exec superset python3 /app/build_dashboard.py       # сборка раскладки
```

После этого в Superset (меню Dashboards) появится дашборд **«Погода — пайплайн данных»**.

Полезные скрипты: `superset/verify_all.py` — проверка запросов чартов,
`superset/fix_charts.py` — точечные правки параметров KPI/gauge.

## 7. Jupyter: анализ (финал пайплайна)

```bash
docker-compose up -d jupyter
# открыть http://localhost:8888, токен входа — weather
```

Ноутбуки монтируются из `./notebooks` в `/home/jovyan/work`. Уже лежит демо
**`demo_weather.ipynb`**: подключение к ClickHouse, базовая статистика, графики
температуры по часам и аномалий по дням.

Добавить свой ноутбук — просто положите `.ipynb` в `./notebooks` (появится в Jupyter
без пересборки).

> Демо-ноутбук устойчив к «устаревшим» данным: окно «последние 24 часа» считается
> от последнего замера в базе, а не от системного времени.

## 8. Генератор данных

Генератор сам создаёт схему и справочник станций, делает **бэкфилл** с `2025-01-01`
до текущего момента (возобновляясь с последнего таймстемпа, без дублей), затем
переходит в **realtime** (1 запись/сек).

```bash
# логи генератора (фаза / прогресс)
docker-compose logs -f generator

# состояние генерации (фаза, текущий таймстемп, прогресс %)
curl localhost:9100/rate

# остановить генератор (graceful)
curl -X POST localhost:9100/stop
```

Сброс данных и повторный бэкфилл:

```bash
docker exec clickhouse clickhouse-client --query "TRUNCATE TABLE weather.readings"
docker-compose restart generator
```

## 9. Проверка, что всё работает

```bash
docker-compose ps                                # все сервисы Up / healthy
curl localhost:9100/rate                         # генератор: mode=realtime, прогресс 100%
docker exec clickhouse clickhouse-client \
  --query "SELECT count(), max(timestamp) FROM weather.readings"   # данные растут
```

Готово: генератор льёт данные → ClickHouse → дашборды в Superset/UI и анализ в Jupyter.

## 10. Остановка и перезапуск

```bash
# остановить все сервисы
docker-compose stop

# полностью удалить контейнеры (данные в volume сохраняются)
docker-compose down

# пересоздать контейнеры из образов (данные ClickHouse/Superset сохраняются в volumes)
docker-compose up -d
```