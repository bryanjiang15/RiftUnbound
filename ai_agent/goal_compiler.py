"""
Goal compiler — deterministic GoalSet → ProfileOverlay.

The LLM strategist (planner) proposes a small GoalSet (what to want); this module
decides the numbers (how much), under a hard whitelist + clamp so a malformed or
hallucinated goal degrades to a no-op instead of an unbounded or crashing weight.

Two bias mechanisms (mirrors schemas.Goal.kind):
- ``weight_bias``  → multiply an existing registry weight (exact, via the line's
  per-term ``score_breakdown``: scaling weight w by m changes that term by
  (m-1)·breakdown[term]).
- ``state_target`` → a GRADED situational bonus over a whitelisted feature metric,
  giving the search a gradient toward the goal rather than a flat plateau.
- ``card_target``  → a flat bonus on lines whose moves play a named card.

The same whitelists drive the planner's goal-vocabulary prompt block
(system_prompt.py), so the menu shown to the LLM can never drift from what the
compiler will actually accept.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from .schemas import Goal, GoalSet

logger = logging.getLogger(__name__)

# ── Tunables (all magnitudes live here, never in the LLM output) ───────────────

MULTIPLIER_MIN = 0.5
MULTIPLIER_MAX = 2.5

# priority → default weight-bias multiplier (used when the LLM omits one)
PRIORITY_MULTIPLIER = {"low": 1.3, "med": 1.7, "high": 2.2}
# priority → situational / card bonus weight
PRIORITY_BONUS_WEIGHT = {"low": 1.5, "med": 3.0, "high": 6.0}

# Profile blocks each registry group writes into (for weight_multipliers keys).
_GROUP_BLOCK = {"state": "state_weights", "action": "action_weights"}

# Whitelisted metrics for state_target goals: feature_key → (is_dict, meaning).
# Keys must exist in ScoreModel.build_score_features() output so both the Python
# re-rank scorer and the engine can evaluate them.
STATE_TARGET_METRICS: dict[str, tuple[bool, str]] = {
    "my_score": (False, "my victory points at end of line"),
    "my_ready_runes": (False, "ready runes left (fuel for reactions)"),
    "reactive_potential": (False, "A/R cards in hand payable with leftover runes"),
    "ready_unit_might_diff": (False, "(my−opp) Might of un-exhausted deployed units"),
    "damage_fragility": (False, "enemy death-progress − mine (higher = enemies closer to dying)"),
    "control_fragility": (False, "my threats on opp battlefields − opp threats on mine"),
    "hold_income": (False, "battlefields I control not yet scored this turn"),
    "rune_development_diff": (False, "(my−opp) channeled runes"),
    "cards_in_hand_net": (False, "asymmetric card advantage"),
    "points_scored": (False, "points gained this turn"),
    "enemy_units_killed": (False, "enemy units removed this turn"),
    "battlefields_conquered": (False, "battlefields newly taken & scored this turn"),
    "bf_control_net": (True, "per-battlefield control: +1 mine / −1 opp / 0 (needs metric_key)"),
    "bf_might_margin": (True, "per-battlefield (my−opp) Might (needs metric_key)"),
}


@dataclass
class ProfileOverlay:
    """A transient, one-turn bias applied on top of the base scoring profile."""

    # "block.weight_key" (e.g. "state_weights.battlefield_control") → multiplier
    weight_multipliers: dict[str, float] = field(default_factory=dict)
    # {id, metric, metric_key, comparator, threshold, weight}
    situational_terms: list[dict[str, Any]] = field(default_factory=list)
    # {id, card_id, weight}
    card_bonuses: list[dict[str, Any]] = field(default_factory=list)
    # human-readable compile diagnostics (accepted + rejected goals)
    notes: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.weight_multipliers or self.situational_terms or self.card_bonuses)

    def to_dict(self) -> dict[str, Any]:
        return {
            "weight_multipliers": self.weight_multipliers,
            "situational_terms": self.situational_terms,
            "card_bonuses": self.card_bonuses,
            "notes": self.notes,
        }


# ── Registry-driven weight-bias whitelist ──────────────────────────────────────

_REGISTRY_CACHE: Optional[dict[str, str]] = None


def _registry_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "Data", "AI", "feature_registry.json",
    )


def weight_bias_features(path: Optional[str] = None) -> dict[str, str]:
    """Registry spec id → profile block, for every top-level scored term.

    A spec id is a valid weight_bias target because it has a single per-term entry
    in ``score_breakdown``, so scaling its weight is an exact, attributable delta.
    Loaded from the exported manifest so it can never drift from the GDScript
    scorer. Falls back to an empty map (every weight_bias becomes a no-op) if the
    manifest is missing.
    """
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is not None and path is None:
        return _REGISTRY_CACHE
    p = path or _registry_path()
    out: dict[str, str] = {}
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        for spec in data.get("specs", []):
            sid = str(spec.get("id", ""))
            block = _GROUP_BLOCK.get(str(spec.get("group", "")))
            if sid and block:
                out[sid] = block
    except FileNotFoundError:
        logger.warning("goal_compiler: feature_registry.json not found at %s; weight_bias disabled", p)
    except Exception as exc:  # noqa: BLE001 — never let a bad manifest crash a decision
        logger.warning("goal_compiler: failed to read feature registry (%s); weight_bias disabled", exc)
    if path is None:
        _REGISTRY_CACHE = out
    return out


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ── Compile ────────────────────────────────────────────────────────────────────


def compile_goals(goal_set: GoalSet | None, *, registry_path: Optional[str] = None) -> ProfileOverlay:
    """Turn a GoalSet into a clamped, whitelisted ProfileOverlay.

    Pure and total: any goal that fails validation is dropped with a note rather
    than raising, so a degenerate LLM output yields (at worst) an empty overlay
    and today's base-profile behaviour.
    """
    overlay = ProfileOverlay()
    if goal_set is None or not goal_set.goals:
        overlay.notes.append("no goals: empty overlay (base profile)")
        return overlay

    wb_features = weight_bias_features(registry_path)
    seen_ids: set[str] = set()

    for goal in goal_set.goals:
        gid = (goal.id or goal.kind).strip() or goal.kind
        if gid in seen_ids:
            overlay.notes.append(f"drop '{gid}': duplicate id")
            continue
        seen_ids.add(gid)
        if goal.kind == "weight_bias":
            _compile_weight_bias(goal, gid, wb_features, overlay)
        elif goal.kind == "state_target":
            _compile_state_target(goal, gid, overlay)
        elif goal.kind == "card_target":
            _compile_card_target(goal, gid, overlay)
        else:  # pragma: no cover — schema Literal prevents this
            overlay.notes.append(f"drop '{gid}': unknown kind {goal.kind!r}")

    return overlay


def _compile_weight_bias(goal: Goal, gid: str, wb_features: dict[str, str], overlay: ProfileOverlay) -> None:
    feat = (goal.feature or "").strip()
    if feat not in wb_features:
        overlay.notes.append(f"drop '{gid}': feature {feat!r} not a registry weight")
        return
    if goal.multiplier is not None:
        mult = _clamp(float(goal.multiplier), MULTIPLIER_MIN, MULTIPLIER_MAX)
    else:
        mult = PRIORITY_MULTIPLIER[goal.priority]
    key = f"{wb_features[feat]}.{feat}"
    # If two goals bias the same weight, keep the stronger lean.
    prev = overlay.weight_multipliers.get(key)
    if prev is None or abs(mult - 1.0) > abs(prev - 1.0):
        overlay.weight_multipliers[key] = mult
    overlay.notes.append(f"weight_bias '{gid}': {key} ×{mult:.2f}")


def _compile_state_target(goal: Goal, gid: str, overlay: ProfileOverlay) -> None:
    metric = (goal.metric or "").strip()
    spec = STATE_TARGET_METRICS.get(metric)
    if spec is None:
        overlay.notes.append(f"drop '{gid}': metric {metric!r} not whitelisted")
        return
    is_dict, _meaning = spec
    metric_key = (goal.metric_key or "").strip()
    if is_dict and not metric_key:
        overlay.notes.append(f"drop '{gid}': metric {metric!r} needs a metric_key (battlefield id)")
        return
    if goal.comparator is None or goal.threshold is None:
        overlay.notes.append(f"drop '{gid}': state_target needs comparator + threshold")
        return
    weight = PRIORITY_BONUS_WEIGHT[goal.priority]
    overlay.situational_terms.append({
        "id": gid,
        "metric": metric,
        "metric_key": metric_key or None,
        "comparator": goal.comparator,
        "threshold": float(goal.threshold),
        "weight": weight,
    })
    target = f"{metric}[{metric_key}]" if metric_key else metric
    overlay.notes.append(f"state_target '{gid}': {target} {goal.comparator} {goal.threshold} (+{weight} graded)")


def _compile_card_target(goal: Goal, gid: str, overlay: ProfileOverlay) -> None:
    card_id = (goal.card_id or "").strip()
    if not card_id:
        overlay.notes.append(f"drop '{gid}': card_target needs card_id")
        return
    weight = PRIORITY_BONUS_WEIGHT[goal.priority]
    overlay.card_bonuses.append({"id": gid, "card_id": card_id, "weight": weight})
    overlay.notes.append(f"card_target '{gid}': play {card_id} (+{weight})")


# ── Graded predicate evaluation (shared by re-rank scorer + tests) ─────────────


def graded_value(metric_value: float, comparator: str, threshold: float) -> float:
    """Map (value, comparator, threshold) → a [0,1] goal-satisfaction score.

    Graded rather than binary so beam search sees a gradient toward the goal:
    a line that gets halfway to the threshold scores ~0.5, not 0.
    """
    scale = max(abs(threshold), 1.0)
    if comparator == ">=":
        if threshold <= 0:
            return 1.0 if metric_value >= threshold else _clamp(1.0 + metric_value / scale, 0.0, 1.0)
        return _clamp(metric_value / threshold, 0.0, 1.0)
    if comparator == "<=":
        return _clamp(1.0 - (metric_value - threshold) / scale, 0.0, 1.0)
    if comparator == "==":
        return _clamp(1.0 - abs(metric_value - threshold) / scale, 0.0, 1.0)
    return 0.0


def _metric_from_features(features: dict[str, Any], metric: str, metric_key: Optional[str]) -> Optional[float]:
    if metric not in features:
        return None
    raw = features[metric]
    if metric_key:
        if not isinstance(raw, dict):
            return None
        if metric_key not in raw:
            return 0.0  # absent battlefield key = neutral, not an error
        raw = raw[metric_key]
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def overlay_delta_breakdown(
    overlay: ProfileOverlay,
    *,
    features: dict[str, Any],
    score_breakdown: dict[str, Any],
    moves: list[str],
) -> dict[str, float]:
    """Per-goal contribution to a line's score delta (keyed by overlay term id).

    Same math as ``overlay_delta`` but returns each term's contribution so logs
    can show WHY a line moved up/down. Sum of values == overlay_delta(...).
    """
    parts: dict[str, float] = {}

    for key, mult in overlay.weight_multipliers.items():
        term_id = key.split(".", 1)[-1]
        term_val = score_breakdown.get(term_id)
        if term_val is None:
            continue
        try:
            parts[term_id] = (mult - 1.0) * float(term_val)
        except (TypeError, ValueError):
            continue

    for term in overlay.situational_terms:
        val = _metric_from_features(features, term["metric"], term.get("metric_key"))
        if val is None:
            continue
        parts[str(term["id"])] = float(term["weight"]) * graded_value(
            val, term["comparator"], float(term["threshold"])
        )

    if overlay.card_bonuses:
        joined = " ".join(moves)
        for bonus in overlay.card_bonuses:
            if bonus["card_id"] in joined:
                parts[str(bonus["id"])] = float(bonus["weight"])

    return parts


def overlay_delta(
    overlay: ProfileOverlay,
    *,
    features: dict[str, Any],
    score_breakdown: dict[str, Any],
    moves: list[str],
) -> float:
    """Score delta this overlay adds to one candidate line (server-side re-rank).

    - weight_bias: exact, (m−1)·breakdown[term] since term = weight·feature.
    - state_target: weight · graded_value(metric, comparator, threshold).
    - card_target: weight if any move string plays the card.
    """
    return sum(overlay_delta_breakdown(
        overlay, features=features, score_breakdown=score_breakdown, moves=moves
    ).values())


def goal_achievement_for_line(
    goal_set: Optional[GoalSet],
    overlay: ProfileOverlay,
    *,
    features: dict[str, Any],
    score_breakdown: dict[str, Any],
    moves: list[str],
) -> tuple[float, dict[str, dict[str, Any]]]:
    """Per-goal leaf achievement for the chosen line + total overlay delta.

    Returns ``(chosen_overlay_delta, {goal_id: {satisfaction, met, delta}})``.
    Satisfaction is graded ``[0, 1]`` for state/card targets; weight_bias uses
    the signed contribution normalized only as present/absent for ``met``.

    When the overlay dropped a goal (empty or partial compile), state/card
    targets still evaluate from the Goal's own metric/comparator/threshold /
    card_id fields so ``chosen_goal_achieved_json`` stays populated.
    """
    parts = overlay_delta_breakdown(
        overlay,
        features=features or {},
        score_breakdown=score_breakdown or {},
        moves=moves or [],
    )
    total_delta = float(sum(parts.values()))
    achieved: dict[str, dict[str, Any]] = {}
    if goal_set is None:
        return total_delta, achieved

    joined = " ".join(moves or [])
    situational = {str(t.get("id")): t for t in overlay.situational_terms}
    card_bonuses = {str(b.get("id")): b for b in overlay.card_bonuses}

    for goal in goal_set.goals:
        gid = str(goal.id)
        if goal.kind == "state_target":
            term = situational.get(gid)
            # Fall back to Goal fields when the overlay dropped this term
            # (empty/partial compile) so achievement is still queryable.
            metric = (term or {}).get("metric") or goal.metric
            metric_key = (term or {}).get("metric_key") or goal.metric_key
            comparator = (term or {}).get("comparator") or goal.comparator
            threshold = (term or {}).get("threshold")
            if threshold is None:
                threshold = goal.threshold
            if metric is None or comparator is None or threshold is None:
                achieved[gid] = {"satisfaction": 0.0, "met": False, "delta": 0.0}
                continue
            val = _metric_from_features(features or {}, metric, metric_key)
            sat = (
                graded_value(val, comparator, float(threshold))
                if val is not None
                else 0.0
            )
            achieved[gid] = {
                "satisfaction": float(sat),
                "met": bool(sat >= 1.0),
                "delta": float(parts.get(gid, 0.0)),
            }
        elif goal.kind == "card_target":
            card_id = str(goal.card_id or (card_bonuses.get(gid) or {}).get("card_id") or "")
            met = bool(card_id and card_id in joined)
            achieved[gid] = {
                "satisfaction": 1.0 if met else 0.0,
                "met": met,
                "delta": float(parts.get(gid, 0.0)),
            }
        elif goal.kind == "weight_bias":
            feature = str(goal.feature or "")
            delta_g = float(parts.get(feature, 0.0)) if feature else 0.0
            achieved[gid] = {
                "satisfaction": 1.0 if abs(delta_g) > 1e-9 else 0.0,
                "met": abs(delta_g) > 1e-9,
                "delta": delta_g,
            }
        else:
            achieved[gid] = {
                "satisfaction": 0.0,
                "met": False,
                "delta": float(parts.get(gid, 0.0)),
            }
    return total_delta, achieved
