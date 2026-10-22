"""Small HTTP client so Hermes lanes and external agents can report into the command center."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class CommandCenterClientError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class CommandCenterClient:
    def __init__(self, base_url: str | None = None, *, token: str | None = None, actor: str = "agent",
                 timeout: float = 10.0) -> None:
        self.base_url = (base_url or os.environ.get("HERMES_CC_URL") or "http://127.0.0.1:4710").rstrip("/")
        self.token = token if token is not None else os.environ.get("HERMES_CC_TOKEN")
        self.actor = actor
        self.timeout = timeout

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        headers = {"Content-Type": "application/json", "X-CC-Actor": self.actor}
        if self.token:
            headers["X-CC-Token"] = self.token
        data = json.dumps(body or {}).encode("utf-8") if method != "GET" else None
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                message = json.loads(exc.read().decode("utf-8")).get("error", "")
            except (ValueError, UnicodeDecodeError):
                message = exc.reason
            raise CommandCenterClientError(exc.code, str(message)) from exc

    def report_output(self, lane_id: str, *, title: str, work_type: str = "other", body: str = "",
                      model: str | None = None, **metrics: Any) -> dict[str, Any]:
        payload = {"title": title, "work_type": work_type, "body": body, "model": model, "author": self.actor}
        payload.update(metrics)
        return self._request("POST", f"/api/lanes/{lane_id}/messages", payload)

    def create_task(self, lane_id: str, title: str, **fields: Any) -> dict[str, Any]:
        return self._request("POST", "/api/tasks", {"lane_id": lane_id, "title": title, **fields})

    def move_task(self, task_id: str, to: str, **fields: Any) -> dict[str, Any]:
        return self._request("POST", f"/api/tasks/{task_id}/transition", {"to": to, **fields})

    def log_experiment(self, experiment_id: str, message: str, level: str = "info") -> dict[str, Any]:
        return self._request("POST", f"/api/experiments/{experiment_id}/events", {"message": message, "level": level})

    def state(self) -> dict[str, Any]:
        return self._request("GET", "/api/state")
