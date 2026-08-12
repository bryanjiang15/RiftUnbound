"""Evidence-based failure-mode classification for searched decisions.

Deterministic signals run first. Eval / search / goal-steering labels upgrade
only with counterfactual evidence. Losses and zero regret alone never imply
eval or search error.
"""
from __future__ import annotations

import json
from typing import Any, Optional

SELECTION_REGRET_EPS = 1e-6

RECOMMENDED_FIX = {
    "reliability": "engine_or_agent_reliability",
    "reasoner_investigation": "reasoner_prompts_or_tool_policy",
    "reasoner_commit": "reasoner_emit_contract",
    "selection_error": "line_selector_prompts",
    "goal_leaf_miss": "strategist_or_selector",
    "search_diagnostics": "search_budget_or_beam",
    "missed_same_turn_goal": "review_counterfactual_line",
    "eval_error": "scoring_weights_or_features",
    "search_coverage_error": "search_budget_beam_or_depth",
    "goal_error": "strategist_prompts_or_overlay",
    "insufficient_evidence": "none_abstain",
}

_DETERMINISTIC_ORDER = (
    "reliability",
    "reasoner_investigation",
    "reasoner_commit",
    "selection_error",
    "goal_leaf_miss",
    "search_diagnostics",
)


def _finding(
    mode: str,
    *,
    confidence: str,
    evidence: list[str],
    decision_key: dict[str, Any],
    recommended_fix_surface: Optional[str] = None,
    upgraded_from: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "confidence": confidence,
        "evidence": evidence,
        "decision_key": decision_key,
        "recommended_fix_surface": recommended_fix_surface or RECOMMENDED_FIX.get(mode, "none"),
        "upgraded_from": upgraded_from,
    }


def _abstention(reason: str, decision_key: dict[str, Any], evidence: Optional[list[str]] = None) -> dict[str, Any]:
    return {
        "mode": "insufficient_evidence",
        "confidence": "abstain",
        "evidence": evidence or [reason],
        "decision_key": decision_key,
        "recommended_fix_surface": RECOMMENDED_FIX["insufficient_evidence"],
        "abstention_reason": reason,
    }


def _decision_key(bundle: dict) -> dict[str, Any]:
    return {
        "game_id": bundle.get("game_id"),
        "turn": bundle.get("turn"),
        "decision_index": bundle.get("decision_index"),
    }


def classify_deterministic(bundle: dict) -> tuple[list[dict], list[dict]]:
    """Return (findings, warnings). Warnings are search diagnostics, not confirmed errors."""
    key = _decision_key(bundle)
    findings: list[dict] = []
    warnings: list[dict] = []
    dec = bundle.get("search_decision") or {}
    eval_m = bundle.get("eval_metrics") or {}
    client = bundle.get("client_metrics") or {}
    reasoner = bundle.get("reasoner") or {}
    candidates = bundle.get("candidates") or []

    parse_retries = int(eval_m.get("parse_retries") or 0)
    legality_retries = int(eval_m.get("legality_retries") or 0)
    fallback_pass = int(eval_m.get("fell_back_to_pass") or 0)
    heuristic = int(client.get("heuristic_fallback") or 0)
    rejection_retries = int(client.get("rejection_retries") or 0)
    selector = str(dec.get("selector_source") or "")
    accepted = client.get("accepted")

    rel_evidence: list[str] = []
    if parse_retries > 0:
        rel_evidence.append(f"parse_retries={parse_retries}")
    if legality_retries > 0:
        rel_evidence.append(f"legality_retries={legality_retries}")
    if rejection_retries > 0:
        rel_evidence.append(f"rejection_retries={rejection_retries}")
    if heuristic:
        rel_evidence.append("heuristic_fallback")
    if fallback_pass:
        rel_evidence.append("fell_back_to_pass")
    if selector == "fallback":
        rel_evidence.append("selector_source=fallback")
    if accepted == 0:
        rel_evidence.append("engine_rejected_final_move")
    if rel_evidence:
        findings.append(_finding("reliability", confidence="high", evidence=rel_evidence, decision_key=key))

    if reasoner:
        inv_ev: list[str] = []
        if reasoner.get("investigation_satisfied") == 0:
            inv_ev.append("investigation_unsatisfied")
        if reasoner.get("local_fork_attempted") == 0 and reasoner.get("comparison_required") == 1:
            inv_ev.append("no_required_local_fork")
        failed = int(reasoner.get("failed_search_calls") or 0)
        recovered = int(reasoner.get("recovered_failed_searches") or 0)
        if failed > recovered:
            inv_ev.append(f"unrecovered_search_failures={failed - recovered}")
        if inv_ev:
            findings.append(_finding(
                "reasoner_investigation", confidence="high", evidence=inv_ev, decision_key=key
            ))
        commit_ev: list[str] = []
        if reasoner.get("committed") == 1 and reasoner.get("chosen_line_complete") == 0:
            commit_ev.append("incomplete_commit")
        if reasoner.get("terminal_kind") == "line" and reasoner.get("committed") == 0:
            commit_ev.append("line_terminal_not_committed")
        if commit_ev:
            findings.append(_finding(
                "reasoner_commit", confidence="high", evidence=commit_ev, decision_key=key
            ))

    regret = dec.get("regret")
    num_cands = int(dec.get("num_candidates") or len(candidates) or 0)
    try:
        regret_f = float(regret) if regret is not None else None
    except (TypeError, ValueError):
        regret_f = None
    if (
        regret_f is not None
        and regret_f > SELECTION_REGRET_EPS
        and num_cands > 1
        and selector not in ("argmax", "")
        and selector != "single"
    ):
        findings.append(_finding(
            "selection_error",
            confidence="high",
            evidence=[
                f"regret={regret_f}",
                f"num_candidates={num_cands}",
                f"selector_source={selector}",
            ],
            decision_key=key,
        ))

    achieved = dec.get("chosen_goal_achieved_json")
    if isinstance(achieved, str):
        try:
            achieved = json.loads(achieved)
        except json.JSONDecodeError:
            achieved = None
    goal_set = dec.get("goal_set_json")
    if goal_set and isinstance(achieved, dict) and achieved:
        missed = [
            gid for gid, rec in achieved.items()
            if isinstance(rec, dict) and rec.get("met") is False
        ]
        if missed:
            findings.append(_finding(
                "goal_leaf_miss",
                confidence="medium",
                evidence=[f"unmet_goals={missed}"],
                decision_key=key,
            ))

    stats = dec.get("search_stats_json")
    if isinstance(stats, str):
        try:
            stats = json.loads(stats)
        except json.JSONDecodeError:
            stats = None
    if isinstance(stats, dict):
        stopped = str(stats.get("stopped_reason") or "")
        diag: list[str] = []
        if stopped in ("node_budget", "time_budget", "seed_exhausted"):
            diag.append(f"stopped_reason={stopped}")
        if num_cands <= 1:
            diag.append(f"degenerate_candidate_count={num_cands}")
        if diag:
            warnings.append(_finding(
                "search_diagnostics",
                confidence="low",
                evidence=diag,
                decision_key=key,
            ))

    return findings, warnings


def _cf_hard_packs(cf_result: Optional[dict]) -> list[dict]:
    if not cf_result or not cf_result.get("ok"):
        return []
    packs_out = []
    for pack in ((cf_result.get("comparison") or {}).get("packs") or []):
        if pack.get("offline_found_hard_match") or pack.get("base_found_hard_match"):
            packs_out.append(pack)
    return packs_out


def classify_with_counterfactual(
    bundle: dict,
    cf_result: Optional[dict] = None,
) -> dict[str, Any]:
    key = _decision_key(bundle)
    findings, warnings = classify_deterministic(bundle)
    abstentions: list[dict] = []
    cf_status = (cf_result or {}).get("status") or ("missing" if not cf_result else "ok")

    hard = _cf_hard_packs(cf_result if cf_status == "ok" else None)
    if cf_result and cf_status not in ("ok", None) and cf_result.get("ok") is False:
        abstentions.append(_abstention(
            f"counterfactual_{cf_status}",
            key,
            evidence=[str(cf_result.get("error") or cf_status)],
        ))

    if hard:
        played_moves = None
        played = next((c for c in (bundle.get("candidates") or []) if c.get("chosen")), None)
        if played:
            from .predicate_packs import canonical_moves
            played_moves = canonical_moves(played.get("moves"))
        for pack in hard:
            pack_id = pack.get("pack_id")
            offline_matches = pack.get("offline_hard_matches") or []
            orig_matches = pack.get("original_hard_matches") or []
            played_already_hard = False
            if played_moves:
                played_already_hard = any(
                    (m.get("canonical_moves") or []) == played_moves
                    for m in (orig_matches + offline_matches)
                )
            if played_already_hard:
                continue
            in_orig = bool(pack.get("best_offline_in_original_beam") or pack.get("original_beam_had_hard_match"))
            orig_hard = bool(pack.get("original_beam_had_hard_match"))
            base_hard = bool(pack.get("base_found_hard_match"))
            overlay_hard = bool(pack.get("offline_found_hard_match"))
            dec = bundle.get("search_decision") or {}
            overlay_present = bool(dec.get("overlay_json"))
            selector = str(dec.get("selector_source") or "")

            if overlay_hard:
                findings.append(_finding(
                    "missed_same_turn_goal",
                    confidence="high",
                    evidence=[f"pack={pack_id}", f"in_original_beam={in_orig}"],
                    decision_key=key,
                ))

            if orig_hard and selector not in ("argmax", "single") and selector:
                # Better line already in original candidate set; selector skipped it.
                findings.append(_finding(
                    "selection_error",
                    confidence="high",
                    evidence=[
                        f"pack={pack_id}",
                        "hard_match_in_original_beam",
                        f"selector_source={selector}",
                    ],
                    decision_key=key,
                    upgraded_from="deterministic_or_new",
                ))
            elif orig_hard:
                # Objectively better original candidate ranked lower by recorded profile.
                findings.append(_finding(
                    "eval_error",
                    confidence="high",
                    evidence=[
                        f"pack={pack_id}",
                        "hard_match_in_original_beam_ranked_below_chosen",
                    ],
                    decision_key=key,
                ))
            elif overlay_hard and not in_orig:
                findings.append(_finding(
                    "search_coverage_error",
                    confidence="high",
                    evidence=[
                        f"pack={pack_id}",
                        "offline_hard_match_absent_from_original_beam",
                    ],
                    decision_key=key,
                ))

            if overlay_present and base_hard and not overlay_hard:
                findings.append(_finding(
                    "goal_error",
                    confidence="high",
                    evidence=[
                        f"pack={pack_id}",
                        "base_profile_found_hard_match_overlay_missed",
                    ],
                    decision_key=key,
                ))

    outcome = (bundle.get("search_decision") or {}).get("game_outcome")
    regret = (bundle.get("search_decision") or {}).get("regret")
    try:
        regret_f = float(regret) if regret is not None else 0.0
    except (TypeError, ValueError):
        regret_f = 0.0
    if outcome == "loss" and regret_f <= SELECTION_REGRET_EPS and not hard:
        abstentions.append(_abstention(
            "loss_or_zero_regret_without_counterfactual",
            key,
            evidence=[f"game_outcome={outcome}", f"regret={regret_f}"],
        ))
    if not findings and not hard:
        abstentions.append(_abstention("no_deterministic_or_counterfactual_signal", key))

    # Deduplicate modes while keeping first (deterministic) then CF upgrades.
    seen: set[tuple] = set()
    uniq: list[dict] = []
    for f in findings:
        sig = (f["mode"], tuple(f.get("evidence") or []))
        if sig in seen:
            continue
        seen.add(sig)
        uniq.append(f)

    return {
        "decision_key": key,
        "findings": uniq,
        "warnings": warnings,
        "abstentions": abstentions,
        "counterfactual_status": cf_status,
    }


def render_markdown(report: dict) -> str:
    key = report.get("decision_key") or {}
    lines = [
        f"# Failure report {key.get('game_id')} t{key.get('turn')} d{key.get('decision_index')}",
        "",
        f"- counterfactual_status: `{report.get('counterfactual_status')}`",
        "",
        "## Findings",
    ]
    findings = report.get("findings") or []
    if not findings:
        lines.append("- (none)")
    for f in findings:
        lines.append(
            f"- **{f.get('mode')}** ({f.get('confidence')}) → `{f.get('recommended_fix_surface')}`"
        )
        for ev in f.get("evidence") or []:
            lines.append(f"  - {ev}")
    lines.append("")
    lines.append("## Warnings")
    warnings = report.get("warnings") or []
    if not warnings:
        lines.append("- (none)")
    for w in warnings:
        lines.append(f"- {w.get('mode')}: {', '.join(w.get('evidence') or [])}")
    lines.append("")
    lines.append("## Abstentions")
    abs_ = report.get("abstentions") or []
    if not abs_:
        lines.append("- (none)")
    for a in abs_:
        lines.append(f"- {a.get('abstention_reason') or a.get('mode')}: {', '.join(a.get('evidence') or [])}")
    lines.append("")
    return "\n".join(lines)
