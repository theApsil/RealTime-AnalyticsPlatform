#!/usr/bin/env python3
"""Общие утилиты для сценариев с ClickHouse (02, 03)."""

from __future__ import annotations

import urllib.request

import clickhouse_connect

from generator.config import ClickHouseSettings

DOCKER_CMD = (
    "docker run -d -p 8123:8123 -p 9000:9000 --name clickhouse "
    "clickhouse/clickhouse-server"
)


def ch_client(settings: ClickHouseSettings):
    return clickhouse_connect.get_client(
        host=settings.host,
        port=settings.port,
        username=settings.user,
        password=settings.password,
        database=settings.database,
    )


def ch_is_ready(settings: ClickHouseSettings, timeout: float = 2.0) -> bool:
    """Проверяет, отвечает ли HTTP-интерфейс ClickHouse на /ping (без авторизации)."""
    url = f"http://{settings.host}:{settings.port}/ping"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def ch_auth_ok(settings: ClickHouseSettings) -> bool:
    """Проверяет, проходит ли авторизация с текущими user/password.

    Подключаемся БЕЗ привязки к базе: иначе `SELECT 1` упадёт с UNKNOWN_DATABASE,
    если база ещё не создана (ошибочно выглядело бы как ошибка авторизации).
    """
    try:
        client = clickhouse_connect.get_client(
            host=settings.host,
            port=settings.port,
            username=settings.user,
            password=settings.password,
        )
        client.command("SELECT 1")
        return True
    except Exception:
        return False
