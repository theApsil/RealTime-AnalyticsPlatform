"""Рантайм-состояние генератора (control plane).

``GeneratorStatus`` — потокобезопасный контейнер состояния, который сервис
обновляет (фаза, текущий таймстемп, прогресс бэкфилла), а ``ControlServer``
отдаёт по HTTP. Через эндпоинт можно также менять размер батча вставки.

Запускается только если в настройках задан ``control_port`` (иначе — no-op).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class GeneratorStatus:
    """Потокобезопасный контейнер состояния генерации."""

    def __init__(self, batch_size: int) -> None:
        self._lock = threading.Lock()
        self._batch_size = int(batch_size)
        self._mode = "init"
        self._current_timestamp: str | None = None
        self._progress_pct = 0.0

    @property
    def batch_size(self) -> int:
        with self._lock:
            return self._batch_size

    def set_batch_size(self, value: int) -> None:
        with self._lock:
            if value < 1:
                raise ValueError("batch_size должен быть >= 1")
            self._batch_size = int(value)

    def update(self, *, mode: str, current_timestamp: datetime, progress_pct: float) -> None:
        with self._lock:
            self._mode = mode
            self._current_timestamp = str(current_timestamp)
            self._progress_pct = round(progress_pct, 1)

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "batch_size": self._batch_size,
                "mode": self._mode,
                "current_timestamp": self._current_timestamp,
                "progress_pct": self._progress_pct,
            }


class ControlServer:
    """HTTP-сервер управления: GET /rate (JSON), POST /rate, POST /stop."""

    def __init__(
        self,
        status: GeneratorStatus,
        host: str,
        port: int,
        stop_event: threading.Event | None = None,
    ) -> None:
        self._status = status
        self._stop_event = stop_event
        self._host = host
        self._port = int(port)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> ControlServer:
        handler = self._make_handler(self._status, self._stop_event)
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
        status: GeneratorStatus, stop_event: threading.Event | None
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

            def do_GET(self) -> None:
                if self.path in ("/rate", "/api/rate"):
                    self._send(200, status.as_dict())
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self) -> None:
                if self.path in ("/rate", "/api/rate"):
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
                    if "batch_size" in payload:
                        status.set_batch_size(payload["batch_size"])
                    self._send(200, status.as_dict())
                except ValueError as exc:
                    self._send(400, {"error": str(exc)})
                except Exception as exc:
                    self._send(400, {"error": f"неверный запрос: {exc}"})

        return Handler
