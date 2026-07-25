"""
search_for metric registry + resolver.

The concrete, entity-scoped predicate vocabulary for the ``search_for`` tool
(docs/schema/search_for_tool_schema.md §5). Deliberately distinct from
``goal_compiler.STATE_TARGET_METRICS`` (scoring heuristics/differentials): these
are absolute board facts a player would name as a goal ("vi-1's Might", "opponent
hand size"), resolved against a candidate line's post-line ``search_state``
snapshot emitted by the engine (``ScoreModel.build_search_state``).

Pure: there is NO game logic here. Every metric just reads the snapshot the engine
already computed, so the engine stays the single source of truth (Phase 1). In
Phase 2 the same registry keys can be resolved engine-side instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from .goal_compiler import graded_value

# Accepted aliases for player-scoped metric targets → canonical seat key.
_PLAYER_ALIASES = {
    "me": "me", "self": "me", "my": "me", "mine": "me", "ai": "me", "us": "me",
    "opponent": "opponent", "opp": "opponent", "enemy": "opponent",
    "them": "opponent", "their": "opponent", "theirs": "opponent", "foe": "opponent",
}

# Relative importance of a clause under combine="weighted".
_WEIGHT_VALUE = {"low": 1.0, "med": 2.0, "high": 3.0}

# Max clauses honored in one search_for call (mirrors the ≤4-goal cap; keeps the
# search from turning into multi-objective soup).
MAX_CONSTRAINTS = 6


@dataclass(frozen=True)
class Resolution:
    """Outcome of extracting one metric value from a search_state."""

    supported: bool
    value: float = 0.0
    reason: str = ""  # why unsupported — surfaced to the model for feedback


@dataclass(frozen=True)
class MetricSpec:
    subject: str  # "unit" | "battlefield" | "player" | "turn" | "card"
    kind: str     # "continuous" | "boolean"
    meaning: str
    extract: Callable[[dict, Optional[str]], Resolution]


# ── Extractors (pure reads over the snapshot) ─────────────────────────────────


def _unit_field(field: str) -> Callable[[dict, Optional[str]], Resolution]:
    def f(state: dict, target: Optional[str]) -> Resolution:
        if not target:
            return Resolution(False, reason="unit metric needs a unit instance id as target")
        u = state.get("units", {}).get(target)
        if u is None:
            # Absent = destroyed / never on board. Its Might/health/damage is 0.
            return Resolution(True, 0.0)
        return Resolution(True, float(u.get(field, 0)))
    return f


def _unit_alive(state: dict, target: Optional[str]) -> Resolution:
    if not target:
        return Resolution(False, reason="unit_alive needs a unit instance id as target")
    return Resolution(True, 1.0 if target in state.get("units", {}) else 0.0)


def _bf_field(field: str) -> Callable[[dict, Optional[str]], Resolution]:
    def f(state: dict, target: Optional[str]) -> Resolution:
        if not target:
            return Resolution(False, reason="battlefield metric needs a battlefield id as target")
        bf = state.get("battlefields", {}).get(target)
        if bf is None:
            return Resolution(False, reason=f"unknown battlefield '{target}'")
        return Resolution(True, float(bf.get(field, 0)))
    return f


def _bf_control(state: dict, target: Optional[str]) -> Resolution:
    if not target:
        return Resolution(False, reason="i_control_battlefield needs a battlefield id as target")
    bf = state.get("battlefields", {}).get(target)
    if bf is None:
        return Resolution(False, reason=f"unknown battlefield '{target}'")
    return Resolution(True, 1.0 if bf.get("i_control") else 0.0)


def _player_field(field: str) -> Callable[[dict, Optional[str]], Resolution]:
    def f(state: dict, target: Optional[str]) -> Resolution:
        who = _PLAYER_ALIASES.get(str(target or "").strip().lower())
        if who is None:
            return Resolution(False, reason="player metric target must be 'me' or 'opponent'")
        p = state.get("players", {}).get(who, {})
        return Resolution(True, float(p.get(field, 0)))
    return f


def _turn_field(field: str) -> Callable[[dict, Optional[str]], Resolution]:
    def f(state: dict, target: Optional[str]) -> Resolution:
        return Resolution(True, float(state.get("turn", {}).get(field, 0)))
    return f


def _card_played(state: dict, target: Optional[str]) -> Resolution:
    if not target:
        return Resolution(False, reason="card_played needs a card instance id as target")
    return Resolution(True, 1.0 if target in state.get("cards_played", []) else 0.0)


# ── Registry (the §5 vocabulary; the tool's metric enum is generated from this) ─

SEARCH_METRICS: dict[str, MetricSpec] = {
    # Unit conditions — target = a unit instance id
    "unit_might":  MetricSpec("unit", "continuous", "the unit's Might after the line", _unit_field("might")),
    "unit_health": MetricSpec("unit", "continuous", "remaining health (Might − damage) after the line", _unit_field("health")),
    "unit_damage": MetricSpec("unit", "continuous", "damage marked on the unit after the line", _unit_field("damage")),
    "unit_alive":  MetricSpec("unit", "boolean", "1 if the unit is still in play after the line, else 0", _unit_alive),
    # Battlefield conditions — target = a battlefield id
    "my_might_on_battlefield":       MetricSpec("battlefield", "continuous", "total Might of my units there after the line", _bf_field("my_might")),
    "opponent_might_on_battlefield": MetricSpec("battlefield", "continuous", "total Might of the opponent's units there", _bf_field("opp_might")),
    "my_units_on_battlefield":       MetricSpec("battlefield", "continuous", "count of my units there", _bf_field("my_units")),
    "opponent_units_on_battlefield": MetricSpec("battlefield", "continuous", "count of opponent units there", _bf_field("opp_units")),
    "i_control_battlefield":         MetricSpec("battlefield", "boolean", "1 if I control it after the line, else 0", _bf_control),
    # Player conditions — target = "me" | "opponent"
    "score":         MetricSpec("player", "continuous", "the player's victory points", _player_field("score")),
    "cards_in_hand": MetricSpec("player", "continuous", "the player's hand size", _player_field("cards_in_hand")),
    "ready_runes":   MetricSpec("player", "continuous", "the player's ready (unexhausted) runes", _player_field("ready_runes")),
    # This-turn outcomes — no target (always me, this turn)
    "points_scored":          MetricSpec("turn", "continuous", "points I scored this turn", _turn_field("points_scored")),
    "enemy_units_killed":     MetricSpec("turn", "continuous", "enemy units I destroyed this turn", _turn_field("enemy_units_killed")),
    "battlefields_conquered": MetricSpec("turn", "continuous", "battlefields I newly took & scored this turn", _turn_field("battlefields_conquered")),
    # Card conditions — target = a card instance id
    "card_played": MetricSpec("card", "boolean", "1 if the named card was played in the line, else 0", _card_played),
}


# ── Clause + line evaluation ──────────────────────────────────────────────────


def _meets(value: float, comparator: str, threshold: float) -> bool:
    if comparator == ">=":
        return value >= threshold
    if comparator == "<=":
        return value <= threshold
    if comparator == "==":
        return value == threshold
    return False


def evaluate_clause(clause: dict, search_state: dict) -> dict:
    """Resolve one clause against a line's search_state → per-clause result dict."""
    metric = str(clause.get("metric", ""))
    comparator = str(clause.get("comparator", ">=") or ">=")
    try:
        threshold = float(clause.get("threshold", 0) or 0)
    except (TypeError, ValueError):
        threshold = 0.0
    target = clause.get("target")
    weight = str(clause.get("weight", "med") or "med").lower()
    label = clause.get("label") or metric or "clause"

    base = {"label": label, "metric": metric, "target": target, "weight": weight}

    spec = SEARCH_METRICS.get(metric)
    if spec is None:
        return {**base, "supported": False, "satisfaction": 0.0, "met": False,
                "reason": f"unknown metric '{metric}'"}

    res = spec.extract(search_state or {}, target)
    if not res.supported:
        return {**base, "supported": False, "satisfaction": 0.0, "met": False,
                "reason": res.reason}

    return {
        **base,
        "supported": True,
        "value": res.value,
        "satisfaction": round(graded_value(res.value, comparator, threshold), 3),
        "met": _meets(res.value, comparator, threshold),
    }


def combine_satisfactions(clause_results: list[dict], mode: str) -> float:
    """Fold per-clause satisfaction into one [0,1] score under the combine mode."""
    sats = [float(c.get("satisfaction", 0.0)) for c in clause_results]
    if not sats:
        return 0.0
    if mode == "any":
        return max(sats)
    if mode == "weighted":
        weights = [_WEIGHT_VALUE.get(c.get("weight", "med"), 2.0) for c in clause_results]
        total = sum(weights)
        if total <= 0:
            return sum(sats) / len(sats)
        return sum(w * s for w, s in zip(weights, sats)) / total
    return min(sats)  # "all" — weakest link (default)


def run_search_for(
    corpus: list[dict],
    constraints: list[dict],
    combine: str = "all",
    top_n: int = 5,
    min_satisfaction: float = 0.0,
) -> dict[str, Any]:
    """Filter a pre-computed candidate-line corpus by a list of predicate clauses.

    Each line carries a ``search_state`` snapshot. Returns matching lines ranked by
    combined satisfaction, with a per-clause breakdown and an actionable ``note``.
    Pure over ``corpus`` — no engine or global state — so it is trivially testable.
    """
    if combine not in {"all", "any", "weighted"}:
        combine = "all"
    if not constraints:
        return {"error": "search_for needs at least one constraint clause.",
                "matches": [], "corpus_size": len(corpus)}
    truncated = len(constraints) > MAX_CONSTRAINTS
    constraints = constraints[:MAX_CONSTRAINTS]
    try:
        top_n = max(1, int(top_n))
    except (TypeError, ValueError):
        top_n = 5
    try:
        min_satisfaction = float(min_satisfaction)
    except (TypeError, ValueError):
        min_satisfaction = 0.0

    matches: list[dict] = []
    for line in corpus:
        state = line.get("search_state") or {}
        clause_results = [evaluate_clause(c, state) for c in constraints]
        matches.append({
            "line_id": line.get("line_id"),
            "moves": line.get("moves", []),
            "score": round(float(line.get("score", 0.0)), 2),
            "satisfaction": round(combine_satisfactions(clause_results, combine), 3),
            "hard_match": all(c.get("supported") and c.get("met") for c in clause_results),
            "clauses": clause_results,
        })

    # Keep lines that clear the bar: strictly positive progress by default, or
    # ``>= min_satisfaction`` when the caller demands a floor (1.0 = fully met only).
    kept = sorted(
        (m for m in matches
         if m["satisfaction"] >= min_satisfaction and m["satisfaction"] > 0.0),
        key=lambda m: (m["satisfaction"], m["score"]),
        reverse=True,
    )[:top_n]

    return {
        "query": {"constraints": constraints, "combine": combine},
        "corpus_size": len(corpus),
        "matches": kept,
        "note": _build_note(matches, kept, constraints, len(corpus), truncated),
    }


def _build_note(
    all_matches: list[dict],
    kept: list[dict],
    constraints: list[dict],
    corpus_size: int,
    truncated: bool,
) -> str:
    if corpus_size == 0:
        return "No candidate lines available to search. Run a turn search first."

    parts: list[str] = []

    # Constraints that no line could even evaluate (bad metric / target) — the most
    # actionable failure, so it leads.
    dead: list[str] = []
    for i in range(len(constraints)):
        if all(not m["clauses"][i]["supported"] for m in all_matches):
            r = all_matches[0]["clauses"][i]
            dead.append(f"'{r['label']}' unusable ({r.get('reason', 'unsupported')})")
    if dead:
        parts.append("Unusable constraints: " + "; ".join(dead) + ".")

    progressed = sum(1 for m in all_matches if m["satisfaction"] > 0.0)
    fully = sum(1 for m in all_matches if m["hard_match"])
    parts.append(f"{progressed}/{corpus_size} lines make progress; {fully} fully satisfy all constraints.")

    # When nothing fully satisfies, name the binding constraint on the best line.
    if fully == 0 and kept:
        best = kept[0]
        misses = [c for c in best["clauses"] if not c.get("met")]
        if misses:
            c = misses[0]
            if c.get("supported"):
                parts.append(f"Best line's binding miss: '{c['label']}' (got {c.get('value')}).")
            else:
                parts.append(f"Best line's binding miss: '{c['label']}' ({c.get('reason')}).")

    if truncated:
        parts.append(f"Only the first {MAX_CONSTRAINTS} constraints were applied.")
    return " ".join(parts)


def metric_enum() -> list[str]:
    """The valid ``metric`` values, for the tool schema (generated, never hand-kept)."""
    return list(SEARCH_METRICS.keys())


def vocabulary_block() -> str:
    """Human-readable metric menu grouped by subject, for the tool description."""
    by_subject: dict[str, list[str]] = {}
    for name, spec in SEARCH_METRICS.items():
        target_hint = {
            "unit": "target=unit id", "battlefield": "target=battlefield id",
            "player": "target=me|opponent", "turn": "no target",
            "card": "target=card id",
        }.get(spec.subject, "")
        by_subject.setdefault(f"{spec.subject} ({target_hint})", []).append(
            f"{name} — {spec.meaning}"
        )
    lines: list[str] = []
    for subject, metrics in by_subject.items():
        lines.append(f"{subject}:")
        lines.extend(f"  - {m}" for m in metrics)
    return "\n".join(lines)
