"""Investigation-quality helpers for the Reasoner and eval adapters.

These metrics measure *how* the Reasoner investigated a turn (novelty, recovery,
score-primary rationales), separate from gold/trap decision quality.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

RESULT_STATUSES = frozenset({
    "evidence",
    "duplicate",
    "illegal_seed",
    "empty",
    "incomplete",
    "unavailable",
})

_SCORE_PRIMARY_RE = re.compile(
    r"("
    r"higher score|highest score|score(?:d)? higher|score gap|"
    r"(?:is\s+)?higher than|"
    r"\d+\.\d+\s*(?:is\s+)?(?:higher than|vs\.?|versus|>|<)\s*\d+\.\d+"
    r")",
    re.IGNORECASE,
)
_STATE_FACT_RE = re.compile(
    r"\b("
    r"point|score race|battlefield|control|unit|kill|trade|hand|"
    r"rune|energy|power|window|contested|flexibility|ready"
    r")\b",
    re.IGNORECASE,
)


def move_tuple(line: dict[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(line, dict):
        return ()
    return tuple(str(m) for m in (line.get("moves", []) or []))


def extract_result_lines(name: str, result: Any) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    raw = (
        result.get("matches", [])
        if name == "search_for"
        else result.get("candidate_lines", [])
    )
    return [line for line in (raw or []) if isinstance(line, dict)]


def classify_search_result(
    name: str,
    result: Any,
    scout_leader: tuple[str, ...] = (),
) -> str:
    """Normalize a search_for/deepen payload into a typed result_status."""
    if name not in {"search_for", "deepen"}:
        return "empty"
    if not isinstance(result, dict):
        return "empty"

    source = str(result.get("source", "") or "")
    if source in {"unavailable", "presim_corpus", "budget_exhausted"}:
        return "unavailable"
    if source == "not_evaluated":
        return "empty"

    error = str(result.get("error", "") or "")
    stopped = str(result.get("stopped_reason", "") or "")
    if result.get("legal") is False or error:
        lowered = error.lower()
        if stopped == "seed_failed" or "seed" in lowered:
            return "illegal_seed"
        if not extract_result_lines(name, result):
            return "empty"

    lines = extract_result_lines(name, result)
    if not lines:
        return "empty"

    seqs = [move_tuple(line) for line in lines]
    if scout_leader and seqs and all(seq == scout_leader for seq in seqs):
        return "duplicate"

    if all(not bool(line.get("complete", True)) for line in lines):
        return "incomplete"

    # Prefer an explicit status from the tool when present and valid.
    explicit = str(result.get("result_status", "") or "")
    if explicit in RESULT_STATUSES:
        return explicit
    return "evidence"


def is_novel_vs_scout(
    name: str,
    result: Any,
    scout_leader: tuple[str, ...],
) -> bool:
    status = classify_search_result(name, result, scout_leader)
    if status not in {"evidence", "incomplete"}:
        return False
    lines = extract_result_lines(name, result)
    if not lines:
        return False
    if not scout_leader:
        return True
    return any(move_tuple(line) != scout_leader for line in lines)


def has_novel_suffix(
    name: str,
    result: Any,
    scout_leader: tuple[str, ...],
    prefix_len: int = 0,
) -> bool:
    """True when a returned line shares a prefix with scout but diverges after."""
    if not scout_leader or prefix_len <= 0:
        return False
    prefix = scout_leader[:prefix_len]
    for line in extract_result_lines(name, result):
        seq = move_tuple(line)
        if seq[:prefix_len] == prefix and seq != scout_leader:
            return True
    return False


def rationale_is_score_primary(rationale: str) -> bool:
    text = (rationale or "").strip()
    if not text:
        return False
    if not _SCORE_PRIMARY_RE.search(text):
        return False
    # State facts in the same rationale mean score is not the sole justification.
    return _STATE_FACT_RE.search(text) is None


def scores_within_tie_band(
    score_a: float | None,
    score_b: float | None,
    band: float,
) -> bool:
    if score_a is None or score_b is None:
        return False
    return abs(float(score_a) - float(score_b)) <= float(band)


def suggest_last_valid_prefix(seed_moves: Iterable[str], error: str = "") -> list[str]:
    """Best-effort repair hint: drop the last seed command after an illegal seed."""
    cmds = [str(m) for m in seed_moves]
    if not cmds:
        return []
    # Keep everything before the final command; the engine already failed at tip.
    if len(cmds) == 1:
        return []
    return cmds[:-1]


def build_feedback_envelope(
    *,
    scout_objective: str = "",
    pivot_step: str = "",
    local_alternative: str = "",
    previous_query: dict[str, Any] | None = None,
    result_status: str = "",
    engine_state_delta: str = "",
    opponent_windows: int = 0,
    tool_error: str = "",
    is_repeat: bool = False,
    forward_progress: bool = False,
    branch_control: str = "",
    revised_hypothesis: str = "",
) -> str:
    """Compact per-round feedback the Reasoner sees after each tool result."""
    query = previous_query or {}
    return (
        "INVESTIGATION FEEDBACK\n"
        f"SCOUT OBJECTIVE: {scout_objective or '(unspecified)'}\n"
        f"PIVOT STEP: {pivot_step or '(unspecified)'}\n"
        f"LOCAL ALTERNATIVE: {local_alternative or '(unspecified)'}\n"
        f"PREVIOUS QUERY: {query}\n"
        f"RESULT STATUS: {result_status or 'empty'}\n"
        f"ENGINE STATE DELTA: {engine_state_delta or '(none reported)'}\n"
        f"OPPONENT WINDOWS: {opponent_windows}\n"
        f"TOOL / SCHEMA ERROR: {tool_error or '(none)'}\n"
        f"IS THIS QUERY A REPEAT: {bool(is_repeat)}\n"
        f"IS FORWARD PROGRESS OCCURRING: {bool(forward_progress)}\n"
        f"REVISED HYPOTHESIS: {revised_hypothesis or '(update after reading status)'}\n"
        f"BRANCH CONTROL: {branch_control or 'continue_current | switch_frontier'}\n"
    )


def advisory_critic_notes(
    *,
    novel_investigation: bool,
    local_fork_attempted: bool,
    failed_queries: int,
    recovered_failures: int,
    result_status: str,
    comparison_required: bool,
) -> list[str]:
    """Rule-based advisory critic — does not override engine legality."""
    notes: list[str] = []
    if not local_fork_attempted and not novel_investigation:
        notes.append(
            "No local fork tested yet. Prefer deepen(line_id, prefix_steps=k) "
            "at the scout pivot before unrelated objectives."
        )
    if result_status == "illegal_seed":
        notes.append(
            "Seed representation failed. This is not evidence for the scout; "
            "retry with a shorter strategic prefix."
        )
    if result_status == "duplicate":
        notes.append(
            "Result duplicated the scout leader. Switch frontier or fork at an "
            "earlier pivot; duplicates do not satisfy investigation."
        )
    if failed_queries and recovered_failures < failed_queries and not novel_investigation:
        notes.append(
            "A prior search-driving call failed without a successful repair. "
            "Recover with a repaired query before terminating."
        )
    if comparison_required:
        notes.append(
            "A distinct alternative exists. Compare concrete resulting-state "
            "deltas with the scout before committing; scores only break ties."
        )
    return notes


def summarize_investigation_trials(trials: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate investigation counters from trial.metrics-like dicts."""
    trials = list(trials)
    eligible = 0
    exemptions: dict[str, int] = {}
    novel = 0
    local_fork = 0
    novel_suffix = 0
    failed_queries = 0
    recovered = 0
    score_primary = 0
    scout_agree = 0
    investigation_ok = 0
    commits = 0
    commit_ok = 0

    for metrics in trials:
        exemption = metrics.get("investigation_exemption")
        if exemption:
            exemptions[str(exemption)] = exemptions.get(str(exemption), 0) + 1
        else:
            eligible += 1
            if metrics.get("novel_investigation"):
                novel += 1
            if metrics.get("local_fork_attempted"):
                local_fork += 1
            if metrics.get("novel_suffix_found"):
                novel_suffix += 1
            if metrics.get("investigation_satisfied"):
                investigation_ok += 1
        failed_queries += int(metrics.get("failed_search_calls", 0) or 0)
        recovered += int(metrics.get("recovered_failed_searches", 0) or 0)
        if metrics.get("score_primary_rationale"):
            score_primary += 1
        if metrics.get("scout_agreement"):
            scout_agree += 1
        if metrics.get("committed") or metrics.get("reasoner_kind") == "line":
            commits += 1
            if metrics.get("chosen_line_complete", True):
                commit_ok += 1

    def rate(n: int, d: int) -> float | None:
        return None if d <= 0 else n / d

    return {
        "trials": len(trials),
        "eligible_turns": eligible,
        "exemptions": exemptions,
        "novel_investigation_rate": rate(novel, eligible),
        "local_fork_rate": rate(local_fork, eligible),
        "novel_suffix_rate": rate(novel_suffix, eligible),
        "investigation_satisfied_rate": rate(investigation_ok, eligible),
        "failed_search_calls": failed_queries,
        "recovered_failed_searches": recovered,
        "failed_query_recovery_rate": rate(recovered, failed_queries),
        "score_primary_rationale_rate": rate(score_primary, len(trials)),
        "scout_agreement_rate": rate(scout_agree, len(trials)),
        "complete_commit_rate": rate(commit_ok, commits),
        "commits": commits,
    }


def render_investigation_report(summary: dict[str, Any], *, title: str = "Investigation report") -> str:
    lines = [
        f"# {title}",
        "",
        f"- trials: {summary.get('trials', 0)}",
        f"- eligible_turns: {summary.get('eligible_turns', 0)}",
        f"- exemptions: {summary.get('exemptions', {})}",
        f"- novel_investigation_rate: {summary.get('novel_investigation_rate')}",
        f"- local_fork_rate: {summary.get('local_fork_rate')}",
        f"- novel_suffix_rate: {summary.get('novel_suffix_rate')}",
        f"- investigation_satisfied_rate: {summary.get('investigation_satisfied_rate')}",
        f"- failed_query_recovery_rate: {summary.get('failed_query_recovery_rate')}",
        f"- score_primary_rationale_rate: {summary.get('score_primary_rationale_rate')}",
        f"- scout_agreement_rate: {summary.get('scout_agreement_rate')}",
        f"- complete_commit_rate: {summary.get('complete_commit_rate')}",
        "",
    ]
    return "\n".join(lines)


def metrics_from_reasoner_telemetry(
    emit: dict[str, Any],
    committed: Optional[dict[str, Any]],
    telemetry: dict[str, Any],
) -> dict[str, Any]:
    """Flatten Reasoner finish telemetry into eval trial.metrics fields."""
    kind = str(emit.get("kind", ""))
    budget = telemetry.get("budget") or {}
    rationale = str(emit.get("rationale", "") or telemetry.get("rationale", "") or "")
    model_calls = int(
        telemetry.get("model_calls")
        or telemetry.get("reasoner_model_calls")
        or 0
    )
    return {
        "model_calls": model_calls,
        "prompt_tokens": int(telemetry.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(telemetry.get("completion_tokens", 0) or 0),
        "total_tokens": int(telemetry.get("total_tokens", 0) or 0),
        "engine_nodes": int(
            telemetry.get("nodes_used", telemetry.get("engine_nodes", 0)) or 0
        ),
        "fallback": kind in {"base_search_fallback", "fallback"},
        "timeout": bool(telemetry.get("timeout", False)),
        "reasoner_kind": kind,
        "committed": committed is not None and kind == "line",
        "chosen_line_complete": bool((committed or {}).get("complete", False))
        if committed
        else False,
        "scout_agreement": bool(telemetry.get("scout_agreement", False)),
        "investigation_satisfied": bool(telemetry.get("investigation_satisfied", False)),
        "investigation_exemption": telemetry.get("investigation_exemption"),
        "unique_sequence_count": int(telemetry.get("unique_sequence_count", 0) or 0),
        "selected_source_lineage": list(telemetry.get("selected_source_lineage") or []),
        "tool_mix": list(telemetry.get("tool_mix") or []),
        "budget_remaining_ms": budget.get("time_remaining_ms"),
        "budget_nodes_remaining": budget.get("nodes_remaining"),
        "budget": budget,
        "novel_investigation": bool(telemetry.get("novel_investigation", False)),
        "local_fork_attempted": bool(telemetry.get("local_fork_attempted", False)),
        "novel_suffix_found": bool(telemetry.get("novel_suffix_found", False)),
        "failed_search_calls": int(telemetry.get("failed_search_calls", 0) or 0),
        "recovered_failed_searches": int(
            telemetry.get("recovered_failed_searches", 0) or 0
        ),
        "score_primary_rationale": bool(
            telemetry.get("score_primary_rationale", rationale_is_score_primary(rationale))
        ),
        "comparison_required": bool(telemetry.get("comparison_required", False)),
        "max_complete_line_length": int(telemetry.get("max_complete_line_length", 0) or 0),
        "reasoner_latency_ms": int(telemetry.get("reasoner_latency_ms", 0) or 0),
    }
