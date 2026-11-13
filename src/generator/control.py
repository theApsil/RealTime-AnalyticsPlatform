"""Рантайм-управление интенсивностью генератора (control plane).

Позволяет менять скорость генерации (batch_size / интервал) на лету, без
перезапуска процесса. ``RateController`` — потокобезопасный изменяемый источник
настроек; ``ControlServer`` — мини-HTTP-сервер на stdlib, через который
веб-интерфейс читает и меняет интенсивность.

Запускается только если в настройках задан ``control_port`` (иначе — no-op).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class RateController:
    """Потокобезопасный изменяемый источник batch_size и интервала."""

    def __init__(self, batch_size: int, interval_seconds: float) -> None:
        self._lock = threading.Lock()
        self._batch_size = int(batch_size)
        self._interval_seconds = float(interval_seconds)

    @property
    def batch_size(self) -> int:
        with self._lock:
            return self._batch_size

    @property
    def interval_seconds(self) -> float:
        with self._lock:
            return self._interval_seconds

    def set_rate(
        self,
        *,
        batch_size: int | None = None,
        interval_seconds: float | None = None,
    ) -> None:
        """Обновляет скорость. Переданные значения валидируются, не переданные — не меняются."""
        with self._lock:
            if batch_size is not None:
                if batch_size < 1:
                    raise ValueError("batch_size должен быть >= 1")
                self._batch_size = int(batch_size)
            if interval_seconds is not None:
                if interval_seconds < 0:
                    raise ValueError("interval_seconds должен быть >= 0")
                self._interval_seconds = float(interval_seconds)

    def as_dict(self) -> dict[str, Any]:
        """Текущее состояние и расчётная скорость (записей/мин)."""
        with self._lock:
            batch_size = self._batch_size
            interval = self._interval_seconds
        rate_per_min = round(batch_size * (60.0 / interval)) if interval > 0 else 0
        return {
            "batch_size": batch_size,
            "interval_seconds": interval,
            "records_per_minute": rate_per_min,
        }


class ControlServer:
    """HTTP-сервер управления: GET/POST /rate (JSON), POST /stop (остановка)."""

    def __init__(
        self,
        rate: RateController,
        host: str,
        port: int,
        stop_event: threading.Event | None = None,
    ) -> None:
        self._rate = rate
        self._stop_event = stop_event
        self._host = host
        self._port = int(port)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> ControlServer:
        handler = self._make_handler(self._rate, self._stop_event)
        self._server = ThreadingHTTPServer((self._host, self._port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="control-server", daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()

    @staticmethod
    def _make_handler(
        rate: RateController, stop_event: threading.Event | None
    ) -> type[BaseHTTPRequestHandler]:
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_: Any) -> None:  # не спамим в лог
                return

            def _send(self, code: int, obj: dict[str, Any]) -> None:
                body = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _route(self) -> bool:
                return self.path in ("/rate", "/api/rate")

            def do_GET(self) -> None:
                if self._route():
                    self._send(200, rate.as_dict())
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self) -> None:
                if self._route():
                    self._handle_rate()
                elif self.path in ("/stop", "/api/stop"):
                    if stop_event is None:
                        self._send(409, {"error": "stop не поддерживается"})
                    else:
                        stop_event.set()
                        self._send(200, {"stopped": True})
                else:
                    self._send(404, {"error": "not found"})

            def _handle_rate(self) -> None:
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    raw = self.rfile.read(length) if length else b"{}"
                    payload = json.loads(raw or b"{}")
                    rate.set_rate(
                        batch_size=payload.get("batch_size"),
                        interval_seconds=payload.get("interval_seconds"),
                    )
                    self._send(200, rate.as_dict())
                except ValueError as exc:
                    self._send(400, {"error": str(exc)})
                except Exception as exc:
                    self._send(400, {"error": f"неверный запрос: {exc}"})

        return Handler
