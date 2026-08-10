"""Build investigation-quality baseline / acceptance reports from eval runs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_agent.investigation_metrics import (
    render_investigation_report,
    summarize_investigation_trials,
)

from .store import EvalStore


def _run_id_from_dir(run_path: Path) -> str:
    manifest = run_path / "manifest.json"
    if manifest.exists():
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if payload.get("run_id"):
            return str(payload["run_id"])
        nested = payload.get("manifest") or {}
        if nested.get("run_id"):
            return str(nested["run_id"])
        summary = payload.get("summary") or {}
        if summary.get("run_id"):
            return str(summary["run_id"])
    return run_path.name


def _metrics_from_jsonl(path: Path) -> list[dict[str, Any]]:
    trials: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        trials.append(dict(row.get("metrics") or {}))
    return trials


def load_trial_metrics(run_dir: Path | str) -> list[dict[str, Any]]:
    run_path = Path(run_dir)
    trials: list[dict[str, Any]] = []

    for name in ("results.jsonl", "trials.jsonl"):
        jsonl = run_path / name
        if jsonl.exists():
            trials = _metrics_from_jsonl(jsonl)
            if trials:
                return trials

    db_path = run_path / "results.db"
    if db_path.exists():
        store = EvalStore(db_path)
        for row in store.list_trials(_run_id_from_dir(run_path)):
            raw = row.get("metrics_json") or "{}"
            metrics = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            trials.append(metrics)
        if trials:
            return trials

    metrics_path = run_path / "metrics.json"
    if metrics_path.exists():
        payload = json.loads(metrics_path.read_text(encoding="utf-8"))
        overall = payload.get("overall") or payload
        inv = overall.get("investigation")
        if isinstance(inv, dict):
            trials.append(inv)
    return trials


def write_investigation_report(
    run_dir: Path | str,
    *,
    title: str = "Reasoner investigation report",
    extra: dict[str, Any] | None = None,
) -> Path:
    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)
    trials = load_trial_metrics(run_path)
    summary = summarize_investigation_trials(trials)
    if extra:
        summary = {**summary, **extra}
    report = render_investigation_report(summary, title=title)
    out_md = run_path / "investigation_report.md"
    out_json = run_path / "investigation_metrics.json"
    out_md.write_text(report, encoding="utf-8")
    out_json.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    return out_md


def archive_baseline_stub(
    runs_dir: Path | str,
    *,
    run_id: str | None = None,
    sample_metrics: list[dict[str, Any]] | None = None,
) -> Path:
    """Archive a structured baseline report (used when live LLM sample is unavailable)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rid = run_id or f"reasoner-investigate-baseline-{stamp}"
    run_path = Path(runs_dir) / rid
    run_path.mkdir(parents=True, exist_ok=True)

    metrics = sample_metrics or _synthetic_baseline_sample()
    jsonl = run_path / "trials.jsonl"
    with jsonl.open("w", encoding="utf-8") as handle:
        for index, row in enumerate(metrics):
            handle.write(
                json.dumps(
                    {
                        "case_id": row.get("case_id", f"synthetic-turn-{index}"),
                        "profile_id": "reasoner-default",
                        "metrics": row,
                    },
                    default=str,
                )
                + "\n"
            )
    manifest = {
        "run_id": rid,
        "kind": "investigation_baseline",
        "note": (
            "Synthetic/archived baseline for investigation metrics plumbing. "
            "Replace by re-running live reasoner-live-smoke or a multi-game "
            "§5.3 sample when Godot + LLM credentials are available."
        ),
        "created_at": stamp,
        "trials": len(metrics),
    }
    (run_path / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    write_investigation_report(
        run_path,
        title="Reasoner investigation baseline (§5.3 harness)",
        extra={"baseline_kind": "archived_stub"},
    )
    return run_path


def _synthetic_baseline_sample() -> list[dict[str, Any]]:
    """≥20 eligible-turn shaped rows across 3 synthetic games for harness smoke."""
    rows: list[dict[str, Any]] = []
    for game in range(3):
        for turn in range(8):
            eligible = turn > 0
            rows.append({
                "case_id": f"game{game}-turn{turn}",
                "investigation_exemption": None if eligible else "forced",
                "novel_investigation": False,
                "local_fork_attempted": False,
                "novel_suffix_found": False,
                "investigation_satisfied": eligible,
                "failed_search_calls": 1 if turn == 2 else 0,
                "recovered_failed_searches": 0,
                "score_primary_rationale": turn in {3, 5},
                "scout_agreement": True,
                "committed": True,
                "chosen_line_complete": True,
                "reasoner_kind": "line",
                "unique_sequence_count": 1,
            })
    return rows
