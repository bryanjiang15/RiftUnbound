"""Risk-adjusted ranking for candidate lines.

Cheap risk (LineRiskProbe) attaches unanswered-leaf risk. This module turns that
into a ranking key the reasoner and argmax share:

  risk_adjusted_score = score + risk_penalty

All risk numbers are signed score impact (negative when an interrupt hurts):
  window_delta = threat_score - pass_score
  risk_worst = most negative window_delta
  risk_expected = sum(window_delta * p_in_hand)
  risk_penalty ≤ 0 when the line is worse under assumed interrupts

Penalty method (belief-weighted by p_in_hand; missing p treated as 1.0):
  - recapture_gap: p * min(0, score_after_recapture - score)
  - pessimistic_worst: plan_broken / needs_recapture → p * risk_worst
  - expected: otherwise risk_expected

score_after_recapture MUST share the original line's decision-time scoring root
(LineRiskProbe re-scores the recovery leaf vs that root). Using TurnSearch's
post-threat-rooted line.score here would mix incompatible baselines: action
deltas would measure from the interrupt state, not from the scout root.

Expand injects the card to search recapture; it does not mean p=1 for ranking.
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable


def _env_on(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "off", "no"}


def risk_rank_enabled() -> bool:
    """Risk-adjusted ranking on by default when line risk is on."""
    if not _env_on("RIFTBOUND_LINE_RISK", True):
        return False
    return _env_on("RIFTBOUND_RISK_RANK", True)


def risk_auto_expand_enabled() -> bool:
    if not risk_rank_enabled():
        return False
    return _env_on("RIFTBOUND_RISK_AUTO_EXPAND", True)


def expand_threshold() -> float:
    try:
        return float(os.environ.get("RIFTBOUND_RISK_EXPAND_THRESHOLD", "1.0"))
    except (TypeError, ValueError):
        return 1.0


def _belief_p(threat: dict[str, Any] | None) -> float:
    """Belief that the assumed card is in hand. Missing p → 1.0 (legacy / explicit assume)."""
    if not isinstance(threat, dict):
        return 1.0
    raw = threat.get("p_in_hand")
    if isinstance(raw, (int, float)):
        return max(0.0, min(1.0, float(raw)))
    return 1.0


def _threat_id(threat: dict[str, Any]) -> str:
    return str(threat.get("card_id") or threat.get("assumed_card") or "")


def _window_delta(threat: dict[str, Any] | None) -> float:
    if not isinstance(threat, dict):
        return 0.0
    return float(threat.get("window_delta") or 0.0)


def _most_harmful_threat(threats: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Threat with the most negative window_delta (largest score drop)."""
    if not threats:
        return None
    return min(threats, key=_window_delta)


def merge_expanded_risk(
    old: dict[str, Any] | None,
    new: dict[str, Any] | None,
) -> dict[str, Any]:
    """Overlay expand recapture onto cheap-probe risk; keep belief p and sibling threats.

    Expand may set p_in_hand=1.0 because it injects the card. That is a search
    assumption, not a new prior — restore the cheap p when the expand reports 1.0.
    """
    if not isinstance(new, dict) or not new:
        return dict(old) if isinstance(old, dict) else {}
    if not isinstance(old, dict) or not old:
        return dict(new)

    old_threats = [t for t in (old.get("threats") or []) if isinstance(t, dict)]
    new_threats = [t for t in (new.get("threats") or []) if isinstance(t, dict)]
    by_id: dict[str, dict[str, Any]] = {}
    for threat in old_threats:
        cid = _threat_id(threat)
        if cid:
            by_id[cid] = dict(threat)

    for threat in new_threats:
        cid = _threat_id(threat)
        if not cid:
            continue
        merged = dict(by_id.get(cid) or {})
        old_p = merged.get("p_in_hand")
        merged.update(threat)
        if (
            isinstance(old_p, (int, float))
            and abs(float(threat.get("p_in_hand") or 0.0) - 1.0) < 1e-9
        ):
            merged["p_in_hand"] = float(old_p)
        by_id[cid] = merged

    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for threat in old_threats:
        cid = _threat_id(threat)
        if not cid:
            ordered.append(dict(threat))
            continue
        ordered.append(by_id.get(cid, dict(threat)))
        seen.add(cid)
    for threat in new_threats:
        cid = _threat_id(threat)
        if cid and cid not in seen:
            ordered.append(by_id.get(cid, dict(threat)))
            seen.add(cid)

    out = dict(old)
    out.update({k: v for k, v in new.items() if k != "threats"})
    out["threats"] = ordered
    worst = 0.0
    expected = 0.0
    needs = bool(old.get("needs_recapture")) or bool(new.get("needs_recapture"))
    can = bool(old.get("can_recapture")) or bool(new.get("can_recapture"))
    for threat in ordered:
        delta = _window_delta(threat)
        worst = min(worst, delta)
        expected += delta * _belief_p(threat)
        needs = needs or bool(threat.get("plan_broken"))
        can = can or bool(threat.get("can_recapture"))
    out["risk_worst"] = worst
    out["risk_expected"] = expected
    out["needs_recapture"] = needs
    out["can_recapture"] = can
    return out


def compute_risk_adjustment(line: dict[str, Any]) -> dict[str, Any]:
    """Compute risk_penalty / risk_adjusted_score / method for one line dict."""
    score = float(line.get("score", 0.0) or 0.0)
    risk = line.get("risk") or {}
    if not isinstance(risk, dict):
        risk = {}
    risk_worst = float(risk.get("risk_worst") or 0.0)
    risk_expected = float(risk.get("risk_expected") or 0.0)
    threats = [t for t in (risk.get("threats") or []) if isinstance(t, dict)]
    worst = _most_harmful_threat(threats)
    recapture = None
    if worst is not None:
        raw = worst.get("score_after_recapture")
        if isinstance(raw, (int, float)):
            recapture = float(raw)
    p = _belief_p(worst)

    if recapture is not None:
        penalty = p * min(0.0, recapture - score)
        method = "recapture_gap"
    elif bool(risk.get("needs_recapture")) or any(
        bool(t.get("plan_broken")) for t in threats
    ):
        penalty = p * risk_worst
        method = "pessimistic_worst"
    else:
        penalty = risk_expected
        method = "expected"

    return {
        "risk_penalty": round(penalty, 3),
        "risk_adjusted_score": round(score + penalty, 3),
        "risk_adjustment_method": method,
    }


def should_auto_expand(risk: dict[str, Any] | None) -> bool:
    if not isinstance(risk, dict) or not risk:
        return False
    if float(risk.get("risk_worst") or 0.0) <= -expand_threshold():
        return True
    if bool(risk.get("needs_recapture")):
        return True
    threats = risk.get("threats") or []
    return any(
        isinstance(t, dict) and bool(t.get("plan_broken")) for t in threats
    )


def apply_risk_adjustment(line: dict[str, Any]) -> dict[str, Any]:
    """Mutate-copy a line with risk adjustment fields."""
    out = dict(line)
    if not risk_rank_enabled():
        out.setdefault("risk_penalty", 0.0)
        out.setdefault("risk_adjusted_score", float(out.get("score", 0.0) or 0.0))
        out.setdefault("risk_adjustment_method", "none")
        out.setdefault("risk_expanded", False)
        return out
    adj = compute_risk_adjustment(out)
    out.update(adj)
    out.setdefault("risk_expanded", False)
    return out


def _line_rank_key(line: dict[str, Any]) -> float:
    if line.get("risk_adjusted_score") is not None:
        return float(line["risk_adjusted_score"])
    return float(line.get("score", 0.0) or 0.0)


def enrich_lines_with_risk(
    lines: list[dict[str, Any]],
    *,
    auto_expand: bool = False,
    expand_fn: Callable[..., dict[str, Any]] | None = None,
    max_expands: int = 2,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Attach risk-adjusted scores; optionally expand top risky lines.

    Returns (enriched_sorted_lines, timing_telemetry).
    """
    started = time.monotonic()
    telemetry: dict[str, Any] = {
        "risk_rank_enabled": risk_rank_enabled(),
        "auto_expand_enabled": bool(auto_expand) and risk_auto_expand_enabled(),
        "auto_expand_count": 0,
        "auto_expand_ms": 0,
        "auto_expand_cards": [],
        "cheap_adjust_ms": 0,
    }
    if not lines:
        telemetry["pre_llm_enrich_ms"] = 0
        return [], telemetry

    adjust_t0 = time.monotonic()
    enriched = [apply_risk_adjustment(dict(line)) for line in lines]
    telemetry["cheap_adjust_ms"] = int((time.monotonic() - adjust_t0) * 1000)

    do_expand = (
        bool(auto_expand)
        and risk_auto_expand_enabled()
        and expand_fn is not None
    )
    if do_expand:
        expand_t0 = time.monotonic()
        # Prefer worst risk among top-3 by raw unanswered score.
        by_score = sorted(
            enriched,
            key=lambda ln: float(ln.get("score", 0.0) or 0.0),
            reverse=True,
        )
        candidates = [
            ln for ln in by_score[:3]
            if should_auto_expand(ln.get("risk") or {})
        ]
        # Expand most-negative risk_worst first, cap at max_expands.
        candidates.sort(
            key=lambda ln: float((ln.get("risk") or {}).get("risk_worst") or 0.0),
        )
        expanded_ids: set[str] = set()
        for ln in candidates[: max(0, int(max_expands))]:
            line_id = str(ln.get("line_id") or "")
            if not line_id or line_id in expanded_ids:
                continue
            risk = ln.get("risk") or {}
            threats = [t for t in (risk.get("threats") or []) if isinstance(t, dict)]
            card_id = ""
            if threats:
                worst = _most_harmful_threat(threats)
                if worst is not None:
                    card_id = str(worst.get("card_id") or worst.get("assumed_card") or "")
            try:
                result = expand_fn(
                    line_id=line_id,
                    card_id=card_id or None,
                    line=ln,
                )
            except TypeError:
                # Older expand_fn signatures without line=
                try:
                    result = expand_fn(line_id=line_id, card_id=card_id or None)
                except Exception:
                    continue
            except Exception:
                continue
            if not isinstance(result, dict) or not result.get("ok"):
                continue
            new_risk = result.get("risk")
            if not isinstance(new_risk, dict):
                continue
            ln["risk"] = merge_expanded_risk(ln.get("risk") or {}, new_risk)
            ln["risk_expanded"] = True
            ln.update(compute_risk_adjustment(ln))
            expanded_ids.add(line_id)
            telemetry["auto_expand_count"] = int(telemetry["auto_expand_count"]) + 1
            if card_id:
                telemetry["auto_expand_cards"].append(card_id)
        telemetry["auto_expand_ms"] = int((time.monotonic() - expand_t0) * 1000)

    enriched.sort(key=_line_rank_key, reverse=True)
    telemetry["pre_llm_enrich_ms"] = int((time.monotonic() - started) * 1000)
    if enriched:
        telemetry["scout_leader_risk_adjusted"] = float(
            enriched[0].get("risk_adjusted_score", enriched[0].get("score", 0.0)) or 0.0
        )
        telemetry["risk_adjusted_leader_id"] = str(enriched[0].get("line_id") or "")
    return enriched, telemetry


def format_pre_llm_banner(
    *,
    scout_ms: int | None = None,
    scout_lines: int | None = None,
    cheap_risk_ms: int | None = None,
    expand_ms: int | None = None,
    expand_count: int | None = None,
    total_ms: int | None = None,
) -> str:
    parts: list[str] = ["Pre-LLM:"]
    if scout_ms is not None:
        bit = f"scout={int(scout_ms)}ms"
        if scout_lines is not None:
            bit += f" lines={int(scout_lines)}"
        parts.append(bit)
    if cheap_risk_ms is not None:
        parts.append(f"cheap_risk={int(cheap_risk_ms)}ms")
    if expand_ms is not None:
        n = int(expand_count or 0)
        parts.append(f"expand={int(expand_ms)}ms n={n}")
    if total_ms is not None:
        parts.append(f"total={int(total_ms)}ms")
    return " | ".join(parts) if len(parts) > 1 else parts[0]
