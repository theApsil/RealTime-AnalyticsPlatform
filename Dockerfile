# Генератор данных — образ приложения.
# Базовый образ тянется через корпоративный прокси-реестр Artifactory
# (docker.io напрямую заблокирован). Для работы вне корпоративной сети
# замените FROM на `python:3.12-slim`.
FROM docker-proxy.artifactory.tcsbank.ru/python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

# Зависимости проекта (см. pyproject.toml).
# --trusted-host нужен в корпоративной сети, где TLS-прокси перехватывает
# pypi.org (self-signed CA). Вне корпоративной сети эти флаги можно убрать
# (или настроить доверие к корпоративному CA / pip-зеркалу).
COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir \
        --trusted-host pypi.org \
        --trusted-host files.pythonhosted.org \
        "clickhouse-connect>=0.8.0" \
        "pydantic-settings>=2.6.0"

# Точка входа: `python -m generator --repository clickhouse`
CMD ["python", "-m", "generator", "--repository", "clickhouse"]