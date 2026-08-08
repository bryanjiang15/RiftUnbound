"""Eval run orchestration and reporting."""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters import resolve_fixture_path, run_adapter
from .corpus import DEFAULT_POSITIONS_DIR, load_corpus, validate_corpus
from .grader import grade_trial
from .metrics import compute_run_metrics
from .schemas import AgentProfile, EvalCase, EvalRunManifest, TrialResult
from .store import EvalStore
from .transforms import available_transforms

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILES_DIR = REPO_ROOT / "Data" / "AI" / "Eval" / "profiles"
DEFAULT_RUNS_DIR = REPO_ROOT / "Data" / "AI" / "Eval" / "runs"


def load_profile(path: Path | str) -> AgentProfile:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return AgentProfile.model_validate(data)


def load_profiles(profile_ids: list[str], profiles_dir: Path | str = DEFAULT_PROFILES_DIR) -> list[AgentProfile]:
    root = Path(profiles_dir)
    profiles: list[AgentProfile] = []
    for pid in profile_ids:
        path = root / f"{pid}.json"
        if not path.exists():
            raise FileNotFoundError(f"profile not found: {path}")
        profiles.append(load_profile(path))
    return profiles


def _uses_llm(profile: AgentProfile) -> bool:
    return profile.adapter in {"reasoner", "goals", "decision"}


def _throttle_ms(manifest: EvalRunManifest) -> int:
    """Delay between LLM-backed trials, env override winning over the manifest."""
    override = os.environ.get("RIFTBOUND_EVAL_THROTTLE_MS", "").strip()
    if override:
        try:
            return max(0, int(override))
        except ValueError:
            pass
    return max(0, manifest.throttle_ms)


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(REPO_ROOT),
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return ""


def run_eval(
    manifest: EvalRunManifest,
    *,
    positions_dir: Path | str = DEFAULT_POSITIONS_DIR,
    profiles_dir: Path | str = DEFAULT_PROFILES_DIR,
    runs_dir: Path | str = DEFAULT_RUNS_DIR,
) -> Path:
    errors = validate_corpus(positions_dir)
    if errors:
        raise RuntimeError("corpus validation failed:\n- " + "\n- ".join(errors))

    cases = load_corpus(
        positions_dir,
        splits=manifest.splits,
        include_fidelity_limited=manifest.include_fidelity_limited,
        eval_lanes=manifest.eval_lanes or None,
        case_globs=manifest.case_globs or None,
    )
    if not cases:
        raise RuntimeError("no cases selected for this manifest")
    profiles = load_profiles(manifest.profiles, profiles_dir)
    if not profiles:
        raise RuntimeError("no profiles selected")

    run_dir = Path(runs_dir) / manifest.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    store = EvalStore(run_dir / "results.db")
    store.start_run(
        run_id=manifest.run_id,
        description=manifest.description,
        mode=manifest.mode,
        manifest=manifest.model_dump(),
        git_sha=_git_sha(),
    )

    transform_names = manifest.transforms or ["identity"]
    for bad in transform_names:
        if bad not in available_transforms():
            raise RuntimeError(f"unknown transform: {bad}")

    results_jsonl = run_dir / "results.jsonl"
    trials: list[TrialResult] = []
    with results_jsonl.open("w", encoding="utf-8") as out_f:
        for profile in profiles:
            store.record_config(manifest.run_id, profile.profile_id, profile.model_dump())
            for case in cases:
                store.record_case_snapshot(manifest.run_id, case.case_id, case.model_dump())
                for transform in transform_names:
                    fixture_override = None
                    if transform != "identity":
                        fixture_override = resolve_fixture_path(
                            case,
                            transform,
                            dest_dir=run_dir / "transformed_fixtures",
                        )
                    for rep in range(manifest.repeats):
                        if trials and _uses_llm(profile):
                            time.sleep(_throttle_ms(manifest) / 1000.0)
                        trial = _run_one(
                            case,
                            profile,
                            repetition=rep,
                            transform=transform,
                            mode=manifest.mode,
                            fixture_override=fixture_override,
                        )
                        trial = grade_trial(case, trial, layers=manifest.layers)
                        store.record_trial(manifest.run_id, trial)
                        trials.append(trial)
                        out_f.write(trial.model_dump_json() + "\n")

    store.finish_run(manifest.run_id)
    summary = store.summary(manifest.run_id)
    run_metrics = compute_run_metrics(trials, cases)
    summary["metrics"] = run_metrics
    (run_dir / "metrics.json").write_text(
        json.dumps(run_metrics, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "manifest": manifest.model_dump(),
                "git_sha": _git_sha(),
                "case_count": len(cases),
                "profile_ids": [p.profile_id for p in profiles],
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "summary": summary,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report = render_report(manifest, trials, summary)
    (run_dir / "report.md").write_text(report, encoding="utf-8")
    return run_dir


def _run_one(
    case: EvalCase,
    profile: AgentProfile,
    *,
    repetition: int,
    transform: str,
    mode: str,
    fixture_override: str | None = None,
) -> TrialResult:
    del mode  # Mode is documentary; the profile.adapter selects mock vs live.
    return run_adapter(
        case,
        profile,
        repetition=repetition,
        transform=transform,
        fixture_override=fixture_override,
    )


def render_report(
    manifest: EvalRunManifest,
    trials: list[TrialResult],
    summary: dict[str, Any],
) -> str:
    lines = [
        f"# Eval Report — `{manifest.run_id}`",
        "",
        manifest.description or "",
        "",
        f"- Mode: `{manifest.mode}`",
        f"- Repeats: {manifest.repeats}",
        f"- Transforms: {', '.join(manifest.transforms or ['identity'])}",
        f"- Trials: {summary.get('trials', len(trials))}",
        "",
        "## Profile summary",
        "",
        "| Profile | Trials | Passed | Errors | Mean score |",
        "|---|---:|---:|---:|---:|",
    ]
    for pid, bucket in sorted(summary.get("by_profile", {}).items()):
        scores = bucket.get("scores") or []
        mean = (sum(scores) / len(scores)) if scores else float("nan")
        mean_s = f"{mean:.3f}" if scores else "n/a"
        lines.append(
            f"| `{pid}` | {bucket['n']} | {bucket['passed']} | {bucket['errors']} | {mean_s} |"
        )

    metrics = summary.get("metrics") or {}
    by_profile_metrics = metrics.get("by_profile") or {}
    if by_profile_metrics:
        lines.extend(
            [
                "",
                "## Metrics",
                "",
                "| Profile | Hard gold | Easy gold | Trap rate | Validity fail | Timeout | p95 latency ms | Mean tokens |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for pid, m in sorted(by_profile_metrics.items()):
            lines.append(
                "| `{pid}` | {hard} | {easy} | {trap} | {val} | {to} | {p95} | {tok} |".format(
                    pid=pid,
                    hard=_fmt_rate(m.get("hard_gold_pass_rate"), m.get("hard_gold_pass"), m.get("hard_gold_n")),
                    easy=_fmt_rate(m.get("easy_gold_pass_rate"), m.get("easy_gold_pass"), m.get("easy_gold_n")),
                    trap=_fmt_rate(m.get("trap_rate"), m.get("trap_hits"), m.get("trap_n")),
                    val=_fmt_pct(m.get("validity_fail_rate")),
                    to=_fmt_pct(m.get("timeout_rate")),
                    p95=_fmt_num(m.get("p95_latency_ms")),
                    tok=_fmt_num(m.get("mean_prompt_tokens")),
                )
            )

    failures = [t for t in trials if not t.overall_pass]
    lines.extend(["", "## Failures", ""])
    if not failures:
        lines.append("None.")
    else:
        for trial in failures[:50]:
            failed_layers = [
                f"{layer.layer}:{layer.details}"
                for layer in trial.layers
                if not layer.passed
            ]
            err = f" error={trial.error}" if trial.error else ""
            lines.append(
                f"- `{trial.case_id}` / `{trial.profile_id}` "
                f"(transform={trial.transform}, rep={trial.repetition}): "
                + "; ".join(failed_layers)
                + err
            )
        if len(failures) > 50:
            lines.append(f"- … and {len(failures) - 50} more")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Hard validity, gold decision quality, cost, and strength are reported separately.",
            "- Silver search agreement is diagnostic and never the sole release gate.",
            "- Free-form rationale text is excluded from trajectory gates.",
            "- `engine_backed` manifests exercise Godot + real adapters; `agent_only` stays mock-safe for CI.",
            "- See `metrics.json` for full numeric aggregates (hard/easy gold, trap rate, latency, tokens).",
            "",
        ]
    )
    return "\n".join(lines)


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{100.0 * value:.1f}%"


def _fmt_rate(rate: float | None, hits: int | None, n: int | None) -> str:
    if rate is None or not n:
        return "n/a"
    return f"{100.0 * rate:.1f}% ({hits or 0}/{n})"


def _fmt_num(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.0f}"
