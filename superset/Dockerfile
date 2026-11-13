# Superset с драйвером ClickHouse.
# Базовый образ тянется через корпоративный прокси-реестр Artifactory
# (docker.io напрямую заблокирован). Вне корпоративной сети замените FROM
# на `apache/superset:latest`.
FROM docker-proxy.artifactory.tcsbank.ru/apache/superset:latest

# Устанавливаем драйвер ClickHouse в venv superset (/app/.venv).
# В venv нет pip, поэтому используем системный pip с `--target` в site-packages venv.
# clickhouse-connect несёт собственный SQLAlchemy-диалект, доступный по URI
# `clickhousedb://` — это рабочая связка с SQLAlchemy 1.4.54.
# ВАЖНО: НЕ использовать `clickhouse://` и НЕ ставить `clickhouse-sqlalchemy` —
# его диалект падает с `ClickHouseDialect_http has no attribute 'dbapi'`
# (несовместимость с SQLAlchemy 1.4.54). Только `clickhousedb://`.
# --trusted-host нужен из-за корпоративного TLS-прокси.
USER root
RUN /usr/local/bin/pip install --no-cache-dir \
        --target=/app/.venv/lib/python3.10/site-packages \
        --trusted-host pypi.org \
        --trusted-host files.pythonhosted.org \
        "clickhouse-connect>=0.8.0"

# Обязательный секрет Superset + отключаем примеры для чистого учебного окружения.
ENV SUPERSET_SECRET_KEY='REAL_TIME_ANALYTICS_PLATFORM_SUPERSET_SECRET' \
    SUPERSET_LOAD_EXAMPLES='no'

# Кастомный entrypoint: перед стартом делает db upgrade + гарантирует админа +
# superset init (иначе после пересоздания контейнера роль Admin остаётся без
# разрешений и все API отдают 403 Forbidden) + ensure_db (подключение ClickHouse).
COPY --chown=superset:superset entrypoint.sh /app/superset-entrypoint.sh
COPY --chown=superset:superset ensure_db.py /app/ensure_db.py
USER root
RUN chmod +x /app/superset-entrypoint.sh
USER superset
EXPOSE 8088
CMD ["/app/superset-entrypoint.sh"]