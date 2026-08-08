"""Spawn and control the Godot EvalPositionRunner host."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_SCRIPT = "res://Scripts/Tools/EvalPositionRunner.gd"
READY_PREFIX = "EVAL_READY:"


def find_godot() -> Optional[str]:
    env = os.environ.get("GODOT", "").strip()
    candidates = [
        env,
        "/Applications/Godot.app/Contents/MacOS/Godot",
        "godot",
        "godot4",
    ]
    for cand in candidates:
        if not cand:
            continue
        path = Path(cand)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        found = shutil.which(cand)
        if found:
            return found
    return None


@dataclass
class GodotHost:
    payload: dict[str, Any]
    process: Optional[subprocess.Popen] = None
    done_path: Optional[Path] = None

    @property
    def engine_port(self) -> Optional[int]:
        port = self.payload.get("engine_port")
        return int(port) if port is not None else None

    def signal_done(self) -> None:
        if self.done_path is not None:
            self.done_path.write_text("done\n", encoding="utf-8")

    def close(self, timeout: float = 15.0) -> None:
        self.signal_done()
        proc = self.process
        if proc is None:
            return
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        self.process = None


def _parse_ready_line(line: str) -> Optional[dict[str, Any]]:
    text = line.strip()
    if not text.startswith(READY_PREFIX):
        return None
    raw = text[len(READY_PREFIX) :]
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError("EVAL_READY payload was not a JSON object")
    return data


def run_godot_oneshot(
    *,
    fixture: str,
    mode: str = "search",
    seat: int = 0,
    search_mode: str = "main",
    node_budget: int = 80,
    time_budget_ms: int = 1000,
    beam_width: int = 8,
    max_depth: int = 8,
    top_n: int = 8,
    seed_moves: Optional[list[str]] = None,
    timeout_s: float = 120.0,
    extra_env: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Run EvalPositionRunner to completion and return the EVAL_READY payload."""
    godot = find_godot()
    if godot is None:
        raise RuntimeError("Godot binary not found (set GODOT)")
    cmd = [
        godot,
        "--headless",
        "--path",
        str(REPO_ROOT),
        "--script",
        EVAL_SCRIPT,
        "--",
        "--fixture",
        fixture,
        "--seat",
        str(seat),
        "--mode",
        mode,
        "--search-mode",
        search_mode,
        "--node-budget",
        str(node_budget),
        "--time-budget-ms",
        str(time_budget_ms),
        "--beam-width",
        str(beam_width),
        "--max-depth",
        str(max_depth),
        "--top-n",
        str(top_n),
    ]
    if seed_moves:
        cmd.extend(["--seed-moves", "|".join(seed_moves)])
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env=env,
        check=False,
    )
    payload = None
    for stream in (proc.stdout or "", proc.stderr or ""):
        for line in stream.splitlines():
            try:
                parsed = _parse_ready_line(line)
            except json.JSONDecodeError:
                continue
            if parsed is not None:
                payload = parsed
    if payload is None:
        raise RuntimeError(
            "EvalPositionRunner produced no EVAL_READY payload\n"
            f"exit={proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    if not payload.get("ok", False):
        raise RuntimeError(f"EvalPositionRunner failed: {payload.get('error', payload)}")
    return payload


@contextmanager
def open_agent_ready_host(
    *,
    fixture: str,
    seat: int = 0,
    search_mode: str = "main",
    node_budget: int = 150,
    time_budget_ms: int = 400,
    beam_width: int = 8,
    max_depth: int = 8,
    top_n: int = 5,
    seed_moves: Optional[list[str]] = None,
    hold_ms: int = 180000,
    ready_timeout_s: float = 90.0,
    extra_env: Optional[dict[str, str]] = None,
) -> Iterator[GodotHost]:
    """Spawn a long-lived agent_ready host and yield once EngineServer is pinned."""
    godot = find_godot()
    if godot is None:
        raise RuntimeError("Godot binary not found (set GODOT)")

    done_file = tempfile.NamedTemporaryFile(prefix="riftbound-eval-done-", delete=False)
    done_path = Path(done_file.name)
    done_file.close()
    if done_path.exists():
        done_path.unlink()

    cmd = [
        godot,
        "--headless",
        "--path",
        str(REPO_ROOT),
        "--script",
        EVAL_SCRIPT,
        "--",
        "--fixture",
        fixture,
        "--seat",
        str(seat),
        "--mode",
        "agent_ready",
        "--search-mode",
        search_mode,
        "--node-budget",
        str(node_budget),
        "--time-budget-ms",
        str(time_budget_ms),
        "--beam-width",
        str(beam_width),
        "--max-depth",
        str(max_depth),
        "--top-n",
        str(top_n),
    ]
    if seed_moves:
        cmd.extend(["--seed-moves", "|".join(seed_moves)])

    env = os.environ.copy()
    env["RIFTBOUND_EVAL_DONE_PATH"] = str(done_path)
    env["RIFTBOUND_EVAL_HOLD_MS"] = str(hold_ms)
    # Prefer ephemeral listen unless caller pinned a port.
    env.setdefault("RIFTBOUND_ENGINE_PORT", "0")
    if extra_env:
        env.update(extra_env)

    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    host = GodotHost(payload={}, process=proc, done_path=done_path)
    try:
        assert proc.stdout is not None
        deadline = time.time() + ready_timeout_s
        payload: Optional[dict[str, Any]] = None
        while time.time() < deadline:
            if proc.poll() is not None:
                rest = proc.stdout.read()
                raise RuntimeError(
                    "agent_ready host exited before EVAL_READY\n"
                    f"exit={proc.returncode}\noutput:\n{rest}"
                )
            line = proc.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue
            try:
                parsed = _parse_ready_line(line)
            except json.JSONDecodeError:
                continue
            if parsed is not None:
                payload = parsed
                break
        if payload is None:
            raise RuntimeError("timed out waiting for EVAL_READY from agent_ready host")
        if not payload.get("ok", False):
            raise RuntimeError(f"agent_ready failed: {payload.get('error', payload)}")
        host.payload = payload
        port = host.engine_port
        if port:
            os.environ["RIFTBOUND_ENGINE_PORT"] = str(port)
        yield host
    finally:
        host.close()
        if done_path.exists():
            try:
                done_path.unlink()
            except OSError:
                pass
