"""Run-level evaluation metrics for report / metrics.json."""
from __future__ import annotations

from typing import Any

from .schemas import EvalCase, TrialResult

_HARD = frozenset({"medium", "hard", "expert"})
_EASY = frozenset({"trivial", "easy"})


def _layer_map(trial: TrialResult) -> dict[str, Any]:
    return {layer.layer: layer for layer in trial.layers}


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] * (1.0 - frac) + ordered[high] * frac


def _rate(numer: int, denom: int) -> float | None:
    if denom <= 0:
        return None
    return numer / denom


def compute_profile_metrics(
    trials: list[TrialResult],
    cases_by_id: dict[str, EvalCase],
) -> dict[str, Any]:
    """Aggregate decision-quality and cost metrics for one profile's trials."""
    n = len(trials)
    hard_gold_n = 0
    hard_gold_pass = 0
    easy_gold_n = 0
    easy_gold_pass = 0
    trap_n = 0
    trap_hits = 0
    validity_fail = 0
    timeout_n = 0
    trajectory_warn = 0
    latencies: list[float] = []
    model_calls: list[float] = []
    prompt_tokens: list[float] = []
    investigation_metrics: list[dict[str, Any]] = []

    for trial in trials:
        case = cases_by_id.get(trial.case_id)
        layers = _layer_map(trial)
        gold = layers.get("gold")
        validity = layers.get("validity")
        cost = layers.get("cost")
        trajectory = layers.get("trajectory")

        if validity is not None and not validity.passed:
            validity_fail += 1
        if cost is not None and bool((cost.details or {}).get("timeout")):
            timeout_n += 1
        if trajectory is not None and not trajectory.passed:
            trajectory_warn += 1

        metrics = trial.metrics or {}
        investigation_metrics.append(metrics)
        if metrics.get("latency_ms") is not None:
            latencies.append(float(metrics["latency_ms"]))
        if metrics.get("model_calls") is not None:
            model_calls.append(float(metrics["model_calls"]))
        if metrics.get("prompt_tokens") is not None:
            prompt_tokens.append(float(metrics["prompt_tokens"]))

        if case is None:
            continue
        if case.fidelity_status != "authoritative":
            continue

        trap_hit = bool(gold and (gold.details or {}).get("trap_hit"))
        if case.trap_outcomes:
            trap_n += 1
            if trap_hit:
                trap_hits += 1

        if gold is None or (gold.details or {}).get("skipped"):
            continue

        gold_passed = bool(gold.passed)
        if case.difficulty in _HARD:
            hard_gold_n += 1
            if gold_passed:
                hard_gold_pass += 1
        elif case.difficulty in _EASY:
            easy_gold_n += 1
            if gold_passed:
                easy_gold_pass += 1

    from ai_agent.investigation_metrics import summarize_investigation_trials

    investigation = summarize_investigation_trials(investigation_metrics)

    return {
        "trials": n,
        "hard_gold_pass_rate": _rate(hard_gold_pass, hard_gold_n),
        "hard_gold_n": hard_gold_n,
        "hard_gold_pass": hard_gold_pass,
        "easy_gold_pass_rate": _rate(easy_gold_pass, easy_gold_n),
        "easy_gold_n": easy_gold_n,
        "easy_gold_pass": easy_gold_pass,
        "trap_rate": _rate(trap_hits, trap_n),
        "trap_n": trap_n,
        "trap_hits": trap_hits,
        "validity_fail_rate": _rate(validity_fail, n),
        "timeout_rate": _rate(timeout_n, n),
        "trajectory_warn_rate": _rate(trajectory_warn, n),
        "mean_latency_ms": _mean(latencies),
        "p95_latency_ms": _percentile(latencies, 95.0),
        "mean_model_calls": _mean(model_calls),
        "mean_prompt_tokens": _mean(prompt_tokens),
        "investigation": investigation,
        "novel_investigation_rate": investigation.get("novel_investigation_rate"),
        "local_fork_rate": investigation.get("local_fork_rate"),
        "novel_suffix_rate": investigation.get("novel_suffix_rate"),
        "failed_query_recovery_rate": investigation.get("failed_query_recovery_rate"),
        "score_primary_rationale_rate": investigation.get("score_primary_rationale_rate"),
        "scout_agreement_rate": investigation.get("scout_agreement_rate"),
        "investigation_satisfied_rate": investigation.get("investigation_satisfied_rate"),
    }


def compute_run_metrics(
    trials: list[TrialResult],
    cases: list[EvalCase],
) -> dict[str, Any]:
    cases_by_id = {c.case_id: c for c in cases}
    by_profile: dict[str, list[TrialResult]] = {}
    for trial in trials:
        by_profile.setdefault(trial.profile_id, []).append(trial)

    profiles = {
        pid: compute_profile_metrics(bucket, cases_by_id)
        for pid, bucket in sorted(by_profile.items())
    }
    # Overall = pool all trials (useful single-profile runs).
    overall = compute_profile_metrics(trials, cases_by_id)
    return {"overall": overall, "by_profile": profiles}
