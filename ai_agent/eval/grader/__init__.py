"""Layered evaluation graders.

Rationale text is never used as a release gate. Observable tools, outcomes,
legality, and cost are the primary signals.
"""
from __future__ import annotations

from typing import Any

from ..schemas import EvalCase, LayerResult, TrialResult


def grade_contract(case: EvalCase, trial: TrialResult) -> LayerResult:
    errors: list[str] = []
    if not case.case_id:
        errors.append("missing case_id")
    if not case.fixture_path:
        errors.append("missing fixture_path")
    if case.label_tier == "gold" and not case.acceptable_outcomes:
        errors.append("gold case has no acceptable outcomes")
    return LayerResult(
        layer="contract",
        passed=not errors,
        score=1.0 if not errors else 0.0,
        details={"errors": errors},
        severity="fail" if errors else "info",
    )


def grade_validity(case: EvalCase, trial: TrialResult) -> LayerResult:
    details: dict[str, Any] = {}
    decision = trial.decision or {}
    emit = trial.reasoner_emit or {}
    errors: list[str] = []

    if trial.error:
        errors.append(f"trial_error: {trial.error}")

    # Hard safety: incomplete/hashless/stale must not look like successes.
    if case.case_id in {"stale-root-rejected", "hashless-line-rejected"}:
        rejected = bool(decision.get("rejected") or emit.get("rejected") or trial.metrics.get("rejected"))
        details["rejected"] = rejected
        if not rejected and not trial.metrics.get("engine_verified_reject"):
            # Mock/deterministic adapters may mark via metrics.
            if not trial.metrics.get("expected_reject"):
                errors.append("expected reject was not recorded")
    else:
        if decision.get("illegal"):
            errors.append("illegal decision")
        if decision.get("incomplete") and decision.get("committed"):
            errors.append("incomplete line was committed")

    for inv in case.hard_invariants:
        ok = _check_invariant(inv.kind, inv.params, case, trial)
        details[inv.kind] = ok
        if not ok:
            errors.append(f"invariant failed: {inv.kind}")

    return LayerResult(
        layer="validity",
        passed=not errors,
        score=1.0 if not errors else 0.0,
        details={"errors": errors, **details},
        severity="fail" if errors else "info",
    )


def grade_gold(case: EvalCase, trial: TrialResult) -> LayerResult:
    if case.fidelity_status != "authoritative":
        return LayerResult(
            layer="gold",
            passed=True,
            score=None,
            details={"skipped": "fidelity_limited_or_excluded", "trap_hit": False},
            severity="info",
        )
    trap_hits = []
    for outcome in case.trap_outcomes or []:
        hit = _check_outcome(outcome.kind, outcome.params, case, trial)
        trap_hits.append(
            {
                "kind": outcome.kind,
                "passed": hit,
                "description": outcome.description,
            }
        )
    trap_hit = any(h["passed"] for h in trap_hits)
    if trap_hit:
        return LayerResult(
            layer="gold",
            passed=False,
            score=0.0,
            details={"trap_hit": True, "traps": trap_hits, "checks": []},
            severity="fail",
        )

    gold = [o for o in case.acceptable_outcomes if o.label_tier == "gold"]
    if not gold:
        return LayerResult(
            layer="gold",
            passed=True,
            score=None,
            details={"skipped": "no_gold_outcomes", "trap_hit": False, "traps": trap_hits},
            severity="info",
        )
    hits = []
    for outcome in gold:
        hits.append(
            {
                "kind": outcome.kind,
                "passed": _check_outcome(outcome.kind, outcome.params, case, trial),
                "description": outcome.description,
            }
        )
    passed = any(h["passed"] for h in hits)
    return LayerResult(
        layer="gold",
        passed=passed,
        score=1.0 if passed else 0.0,
        details={"trap_hit": False, "traps": trap_hits, "checks": hits},
        severity="fail" if not passed else "info",
    )


def grade_silver(case: EvalCase, trial: TrialResult) -> LayerResult:
    silver = [o for o in case.acceptable_outcomes if o.label_tier == "silver"]
    search_agreement = trial.metrics.get("search_agreement")
    details: dict[str, Any] = {"search_agreement": search_agreement}
    if silver:
        hits = [
            {
                "kind": o.kind,
                "passed": _check_outcome(o.kind, o.params, case, trial),
            }
            for o in silver
        ]
        details["checks"] = hits
        passed = any(h["passed"] for h in hits)
        return LayerResult(
            layer="silver",
            passed=passed,
            score=1.0 if passed else 0.0,
            details=details,
            severity="warn" if not passed else "info",
        )
    if search_agreement is None:
        return LayerResult(
            layer="silver",
            passed=True,
            score=None,
            details={"skipped": "no_silver_signal"},
            severity="info",
        )
    # Diagnostic only — never a hard release gate by itself.
    return LayerResult(
        layer="silver",
        passed=True,
        score=float(search_agreement),
        details=details,
        severity="info",
    )


def grade_trajectory(case: EvalCase, trial: TrialResult) -> LayerResult:
    trace = trial.tool_trace or []
    names = [str(t.get("name", "")) for t in trace]
    ritual = _count_ritual_calls(names)
    details = {
        "tool_count": len(trace),
        "tool_names": names,
        "ritual_calls": ritual,
        "rationale_excluded": True,
    }
    # Empty traces are fine for argmax/mock adapters.
    passed = ritual == 0
    return LayerResult(
        layer="trajectory",
        passed=passed,
        score=1.0 if passed else max(0.0, 1.0 - 0.25 * ritual),
        details=details,
        severity="warn" if not passed else "info",
    )


def grade_cost(case: EvalCase, trial: TrialResult) -> LayerResult:
    metrics = trial.metrics or {}
    details = {
        "latency_ms": metrics.get("latency_ms", 0),
        "model_calls": metrics.get("model_calls", 0),
        "prompt_tokens": metrics.get("prompt_tokens", 0),
        "completion_tokens": metrics.get("completion_tokens", 0),
        "engine_nodes": metrics.get("engine_nodes", 0),
        "fallback": bool(metrics.get("fallback")),
        "timeout": bool(metrics.get("timeout")),
    }
    passed = not details["timeout"]
    return LayerResult(
        layer="cost",
        passed=passed,
        score=None,
        details=details,
        severity="fail" if not passed else "info",
    )


def grade_trial(case: EvalCase, trial: TrialResult, layers: list[str] | None = None) -> TrialResult:
    selected = layers or [
        "contract",
        "validity",
        "gold",
        "silver",
        "trajectory",
        "cost",
    ]
    graders = {
        "contract": grade_contract,
        "validity": grade_validity,
        "gold": grade_gold,
        "silver": grade_silver,
        "trajectory": grade_trajectory,
        "cost": grade_cost,
    }
    results: list[LayerResult] = []
    for name in selected:
        fn = graders.get(name)
        if fn is None:
            continue
        results.append(fn(case, trial))
    hard_fail = any(
        r.severity == "fail" and not r.passed for r in results if r.layer in {"contract", "validity", "gold", "cost"}
    )
    scored = [r.score for r in results if r.score is not None]
    trial.layers = results
    trial.overall_pass = not hard_fail and all(
        r.passed for r in results if r.layer in {"contract", "validity"}
    )
    trial.overall_score = (sum(scored) / len(scored)) if scored else None
    return trial


def _check_invariant(kind: str, params: dict[str, Any], case: EvalCase, trial: TrialResult) -> bool:
    metrics = trial.metrics or {}
    decision = trial.decision or {}
    if kind in {
        "chosen_line_complete",
        "root_hash_matched",
        "live_state_unchanged",
        "legal_choice",
        "reactive_mode",
        "command_legal",
        "legal_move_contains",
        "score_cap_behavior",
        "combat_window",
        "chosen_line_legal",
        "target_legal",
        "has_candidates",
        "incomplete_not_committed",
        "commit_accepted",
        "stale_root_rejected",
        "hashless_line_rejected",
    }:
        # Prefer explicit metric flags set by adapters / Godot runner.
        if kind in metrics:
            return bool(metrics[kind])
        if kind == "chosen_line_complete":
            return bool(decision.get("complete", metrics.get("complete", True)))
        if kind == "has_candidates":
            return int(metrics.get("candidate_count", decision.get("candidate_count", 1))) > 0
        if kind == "incomplete_not_committed":
            return not (decision.get("incomplete") and decision.get("committed"))
        if kind in {"stale_root_rejected", "hashless_line_rejected"}:
            return bool(metrics.get("expected_reject") or decision.get("rejected"))
        # Deterministic mock path treats unspecified invariants as satisfied when
        # the adapter marked engine_ok.
        return bool(metrics.get("engine_ok", True))
    return bool(metrics.get(kind, True))


def _check_outcome(kind: str, params: dict[str, Any], case: EvalCase, trial: TrialResult) -> bool:
    metrics = trial.metrics or {}
    decision = trial.decision or {}
    command = str(decision.get("command") or decision.get("move_command") or metrics.get("command") or "")
    chosen_moves = [str(m) for m in (metrics.get("chosen_moves") or decision.get("moves") or [])]
    if not chosen_moves and command:
        chosen_moves = [command]
    line_blob = " | ".join(chosen_moves)

    # Parametric line checks must run before the `kind in metrics` shortcut.
    if kind == "line_contains":
        return str(params.get("substring", "")) in line_blob

    if kind in metrics:
        return bool(metrics[kind])
    if kind == "wins_game":
        return bool(metrics.get("wins_game") or decision.get("wins_game"))
    if kind == "score_after_at_least":
        got = metrics.get("my_score_after", decision.get("my_score_after"))
        return got is not None and int(got) >= int(params.get("my_score_after", 0))
    if kind == "score_after_equals":
        got = metrics.get("my_score_after", decision.get("my_score_after"))
        return got is not None and int(got) == int(params.get("my_score_after", 0))
    if kind == "command_equals":
        return command == str(params.get("command", ""))
    if kind == "has_complete_candidates":
        return int(metrics.get("complete_candidate_count", metrics.get("candidate_count", 0))) > 0
    if kind == "has_candidates":
        return int(metrics.get("candidate_count", 0)) > 0
    if kind == "terminal_reason":
        return str(metrics.get("terminal_reason") or decision.get("terminal_reason") or "") == str(
            params.get("terminal_reason", "")
        )
    if kind == "command_prefix":
        return command.startswith(str(params.get("prefix", "")))
    if kind == "command_contains":
        return str(params.get("substring", "")) in command
    if kind == "discard_card":
        return str(params.get("card_id", "")) in command
    if kind == "no_end_turn_opener":
        first = str(metrics.get("first_move") or command)
        return first != "end turn" and not first.startswith("move ")
    if kind == "incomplete_budget_cutoff":
        return (
            bool(metrics.get("incomplete") or decision.get("incomplete"))
            and str(metrics.get("terminal_reason", "")) == str(params.get("terminal_reason", "node_budget"))
        )
    if kind in {
        "reject_stale_root",
        "reject_hashless",
        "conquers_if_unanswered",
        "score_remains",
        "attacker_survives_trade",
        "develops_via_discard",
        "gust_valid_target",
        "turn_advances",
        "seeded_jinx_auto_choices",
    }:
        return bool(metrics.get(kind, metrics.get("engine_ok", False)))
    return bool(metrics.get("engine_ok", False))


def _count_ritual_calls(names: list[str]) -> int:
    if len(names) < 4:
        return 0
    # Same tool repeated 3+ times consecutively without progress.
    ritual = 0
    streak = 1
    for i in range(1, len(names)):
        if names[i] == names[i - 1] and names[i] in {"evaluate_position", "search_turn"}:
            streak += 1
            if streak >= 3:
                ritual += 1
        else:
            streak = 1
    return ritual
