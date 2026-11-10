# Superset с драйвером ClickHouse.
# Базовый образ тянется через корпоративный прокси-реестр Artifactory
# (docker.io напрямую заблокирован). Вне корпоративной сети замените FROM
# на `apache/superset:latest`.
FROM docker-proxy.artifactory.tcsbank.ru/apache/superset:latest

# Устанавливаем драйвер ClickHouse в venv superset (/app/.venv).
# В venv нет pip, поэтому используем системный pip с `--target` в site-packages venv.
# clickhouse-sqlalchemy==0.3.2 требует SQLAlchemy 1.4.x — в venv уже 1.4.54, без конфликта.
# --trusted-host нужен из-за корпоративного TLS-прокси.
USER root
RUN /usr/local/bin/pip install --no-cache-dir \
        --target=/app/.venv/lib/python3.10/site-packages \
        --trusted-host pypi.org \
        --trusted-host files.pythonhosted.org \
        "clickhouse-connect>=0.8.0" \
        "clickhouse-sqlalchemy==0.3.2"

# Обязательный секрет Superset + отключаем примеры для чистого учебного окружения.
ENV SUPERSET_SECRET_KEY='REAL_TIME_ANALYTICS_PLATFORM_SUPERSET_SECRET' \
    SUPERSET_LOAD_EXAMPLES='no'

USER superset
EXPOSE 8088