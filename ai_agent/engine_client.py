"""
Phase 2 — HTTP client for the live Godot engine server.

Godot's EngineServer (default 127.0.0.1:8766) exposes:
  GET  /engine/health
  POST /engine/simulate  {moves: [...], seat?: int}
  POST /engine/search    {budget?, top_n?, mode?, seed_moves?, ...}
  POST /engine/expand_risk {line, card_id?, ...}

Skills prefer these live endpoints and fall back to Phase-1 pre-computed
lookups when the engine is unreachable (§6 fail-safe).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional

DEFAULT_ENGINE_PORT = 8766
DEFAULT_TIMEOUT_S = 8.0


def _port() -> int:
    raw = os.environ.get("RIFTBOUND_ENGINE_PORT", "").strip()
    if raw and raw.isdigit() and int(raw) > 0:
        return int(raw)
    return DEFAULT_ENGINE_PORT


def base_url() -> str:
    # Always IPv4 loopback — matches EngineServer.bind("127.0.0.1").
    return f"http://127.0.0.1:{_port()}"


def _timeout_s() -> float:
    raw = os.environ.get("RIFTBOUND_ENGINE_TIMEOUT_S", "").strip()
    if raw:
        try:
            return max(0.5, float(raw))
        except ValueError:
            pass
    return DEFAULT_TIMEOUT_S


def _request(
    method: str,
    path: str,
    body: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> dict[str, Any]:
    """Issue an HTTP request. Raises EngineUnavailable on transport/HTTP errors."""
    url = base_url() + path
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout if timeout is not None else _timeout_s()) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return {}
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            return {"result": parsed}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            pass
        raise EngineUnavailable(f"HTTP {e.code} from {path}: {detail or e.reason}") from e
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        raise EngineUnavailable(f"engine unreachable at {url}: {e}") from e


class EngineUnavailable(Exception):
    """Raised when the Godot engine server cannot be reached or returned an error."""


def health() -> bool:
    """Return True if /engine/health responds ok."""
    try:
        payload = _request("GET", "/engine/health", timeout=1.5)
        return bool(payload.get("ok"))
    except EngineUnavailable:
        return False


def simulate(moves: list[str], seat: Optional[int] = None) -> dict[str, Any]:
    """POST /engine/simulate — run MoveSimulator.simulate_line on the pinned state."""
    body: dict[str, Any] = {"moves": list(moves)}
    if seat is not None:
        body["seat"] = seat
    return _request("POST", "/engine/simulate", body)


def search(payload: dict[str, Any]) -> dict[str, Any]:
    """POST /engine/search — run TurnSearch on the pinned state."""
    return _request("POST", "/engine/search", payload)


def rollout(payload: dict[str, Any], timeout: Optional[float] = None) -> dict[str, Any]:
    """POST /engine/rollout — bounded multi-turn / reactive outcome tree.

    Rollouts keep the engine busy for the full search budget plus JSON
    serialize, so callers should pass an explicit timeout. Default is 3 minutes.
    """
    return _request("POST", "/engine/rollout", payload, timeout=timeout if timeout is not None else 180.0)


def expand_risk(payload: dict[str, Any]) -> dict[str, Any]:
    """POST /engine/expand_risk — recapture search after an assumed interrupt."""
    return _request("POST", "/engine/expand_risk", payload)
