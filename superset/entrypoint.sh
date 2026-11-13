#!/usr/bin/env bash
#
# Самоинициализация Superset перед стартом сервера.
# Стандартный CMD образа (run-server.sh) просто запускает gunicorn и НЕ выполняет
# `superset init`. Если роль Admin не получила разрешения (например, после
# пересоздания контейнера или при свежем volume superset_home), все API
# отдают 403 Forbidden. Этот entrypoint доводит БД до нужного состояния.
set -euo pipefail

echo "[superset-entrypoint] db upgrade"
superset db upgrade || echo "[superset-entrypoint] db upgrade: пропущено"

echo "[superset-entrypoint] ensure admin (${SUPERSET_ADMIN_USER:-admin})"
superset fab create-admin \
    --username "${SUPERSET_ADMIN_USER:-admin}" \
    --firstname Admin \
    --lastname User \
    --email "${SUPERSET_ADMIN_EMAIL:-admin@example.com}" \
    --password "${SUPERSET_ADMIN_PASSWORD:-admin}" \
    >/dev/null 2>&1 || echo "[superset-entrypoint] admin уже существует"

echo "[superset-entrypoint] init (разрешения)"
superset init || echo "[superset-entrypoint] init: пропущено/ошибка"

echo "[superset-entrypoint] ensure ClickHouse db connection"
/usr/local/bin/python3 /app/ensure_db.py || echo "[superset-entrypoint] ensure_db: ошибка"

echo "[superset-entrypoint] запуск сервера"
exec /app/docker/entrypoints/run-server.sh "$@"