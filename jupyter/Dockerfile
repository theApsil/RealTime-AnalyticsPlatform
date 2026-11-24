# Jupyter для анализа данных платформы.
# Базовый образ тянется через корпоративный прокси-реестр Artifactory
# (docker.io напрямую заблокирован). Вне корпоративной сети замените FROM
# на `jupyter/scipy-notebook:latest`.
#
# scipy-notebook уже содержит pandas, matplotlib, numpy и scipy — тяжёлые
# библиотеки анализа не приходится ставить через pip (это медленно/нестабильно
# через корпоративный прокси). Через pip доставляем только лёгкий драйвер
# ClickHouse.
FROM docker-proxy.artifactory.tcsbank.ru/jupyter/scipy-notebook:latest

# Драйвер ClickHouse для подключения к БД из ноутбука.
# --trusted-host нужен из-за корпоративного TLS-прокси.
USER root
RUN pip install --no-cache-dir \
        --trusted-host pypi.org \
        --trusted-host files.pythonhosted.org \
        "clickhouse-connect>=0.8.0"
USER jovyan

# Папка с ноутбуками монтируется как /home/jovyan/work