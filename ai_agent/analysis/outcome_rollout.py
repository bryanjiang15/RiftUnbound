"""Multi-turn outcome-based counterfactual orchestration."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .. import engine_client
from ..memory import Memory
from . import counterfactual as cf
from . import outcome_tiers
from . import predicate_packs as packs
from .context import diversify_roots, json_load, normalize_engine_lines, write_temp_json
from .rollout_contracts import (
    HARD_CAP_FUTURE_PLAYER_TURNS,
    HORIZON_MULTI_TURN,
    INFORMATION_ORACLE,
    OPPONENT_POLICY_ORACLE,
    RESULT_SCHEMA_V2,
    RolloutBudget,
    RolloutResult,
    clamp_future_player_turns,
    resolve_budget,
    v2_assumptions,
)

STATUS_OK = cf.STATUS_OK
STATUS_UNSUPPORTED = cf.STATUS_UNSUPPORTED
STATUS_HASH_MISMATCH = cf.STATUS_HASH_MISMATCH
STATUS_ENGINE_ERROR = cf.STATUS_ENGINE_ERROR
STATUS_NO_SNAPSHOT = cf.STATUS_NO_SNAPSHOT


def default_target(bundle: dict) -> dict[str, Any]:
    return {"kind": "win", "label": "win_game"}


def run_offline_rollout(
    *,
    roots: list[dict],
    future_player_turns: int,
    budget: RolloutBudget,
    overlay: Optional[dict] = None,
    profile_path: str = "",
    seat: Optional[int] = None,
    profile_path_by_seat: Optional[dict] = None,
    until_turn_number: Optional[int] = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "future_player_turns": clamp_future_player_turns(future_player_turns),
        "roots": [
            {
                "line_id": r.get("line_id"),
                "moves": r.get("moves") or [],
                "source": r.get("source"),
                "score": r.get("score"),
            }
            for r in roots
        ],
        "budget": budget.to_dict(),
    }
    if overlay:
        body["overlay"] = overlay
    if profile_path:
        body["profile_path"] = profile_path
    if profile_path_by_seat:
        body["profile_path_by_seat"] = profile_path_by_seat
    if seat is not None:
        body["seat"] = seat
    if until_turn_number:
        body["until_turn_number"] = int(until_turn_number)
    # Search budget is only the Godot worker's think time. Serialize + HTTP of
    # a multi-turn tree is extra, and a 4-turn oracle rollout routinely exceeds
    # global_time_ms + 10s (the old cap), which urllib then reports as timeout.
    timeout = max(180.0, budget.global_time_ms / 1000.0 + 120.0)
    return engine_client.rollout(body, timeout=timeout)


def analyze_outcome_rollout(
    memory: Memory,
    *,
    game_id: str,
    turn: int,
    decision_index: int,
    future_player_turns: int = 4,
    preset: str = "deep",
    budget_overrides: Optional[dict] = None,
    target: Optional[dict] = None,
    persist: bool = True,
    host_factory=None,
    include_same_turn: bool = True,
) -> dict[str, Any]:
    """Run multi-turn oracle rollout; fall back to same-turn CF on failure."""
    bundle = cf.load_decision_bundle(
        memory, game_id=game_id, turn=turn, decision_index=decision_index
    )
    budget = resolve_budget(preset, budget_overrides)
    turns = clamp_future_player_turns(future_player_turns, HARD_CAP_FUTURE_PLAYER_TURNS)
    status = cf.snapshot_status(bundle)
    snap = bundle.get("snapshot") or {}
    expected_hash = str(snap.get("root_state_hash") or "")
    profile_json, overlay = cf.reconstruct_profile(bundle)
    tgt = dict(target or default_target(bundle))
    until_turn = 0
    if outcome_tiers.is_maximize_target(tgt):
        tgt.setdefault("metric", "position")
        tgt.setdefault("label", "max_score_after_turns")
        until_turn = outcome_tiers.until_turn_number(tgt)
        if until_turn <= 0:
            # Legacy: N was a relative player-turn count. Treat the request as
            # "finish the turn that is current+N-1".
            rel = outcome_tiers.required_player_turns(tgt) or turns
            until_turn = max(int(turn), int(turn) + int(rel) - 1)
        until_turn = max(int(turn), int(until_turn))
        turns = outcome_tiers.horizon_player_turns_for_until(
            current_turn=int(turn),
            until_turn=until_turn,
            hard_cap=HARD_CAP_FUTURE_PLAYER_TURNS,
        )
        reachable = int(turn) + int(turns) - 1
        tgt["until_turn"] = min(int(until_turn), reachable)
        tgt["after_player_turns"] = turns
        until_turn = int(tgt["until_turn"])
    assumptions = v2_assumptions(future_player_turns=turns, budget=budget)
    if until_turn:
        assumptions["until_turn"] = until_turn
    search_inputs = {
        "mode": "outcome_rollout",
        "future_player_turns": turns,
        "preset": preset,
        **budget.to_dict(),
        "target": tgt,
    }
    profile_inputs = {
        "weight_version_id": (bundle.get("search_decision") or {}).get("weight_version_id"),
        "has_overlay": bool(overlay),
        "goals_source": (bundle.get("search_decision") or {}).get("goals_source"),
        "profile_assumption": "recorded_or_default",
    }

    def _persist(status_val: str, result: dict) -> dict:
        result = {
            **result,
            "status": status_val,
            "game_id": game_id,
            "turn": turn,
            "decision_index": decision_index,
            "assumptions": result.get("assumptions") or assumptions,
            "result_schema_version": RESULT_SCHEMA_V2,
            "run_kind": "outcome_rollout",
            "future_player_turns": turns,
        }
        if persist:
            memory.record_counterfactual_run(
                game_id=game_id,
                turn=turn,
                decision_index=decision_index,
                root_state_hash=expected_hash or result.get("root_state_hash"),
                predicate_pack_version=packs.PREDICATE_PACK_VERSION,
                search_inputs=search_inputs,
                profile_inputs=profile_inputs,
                budget=budget.to_dict(),
                assumptions=result.get("assumptions") or assumptions,
                status=status_val,
                result=result,
                run_kind="outcome_rollout",
                result_schema_version=RESULT_SCHEMA_V2,
                future_player_turns=turns,
                opponent_policy=OPPONENT_POLICY_ORACLE,
            )
        return result

    if status != STATUS_OK:
        # Same-turn path also abstains; surface readiness clearly.
        fallback = None
        if include_same_turn:
            fallback = cf.analyze_same_turn_decision(
                memory,
                game_id=game_id,
                turn=turn,
                decision_index=decision_index,
                persist=False,
                host_factory=host_factory,
                bundle=bundle,
            )
        return _persist(status, {
            "ok": False,
            "error": status,
            "horizon": HORIZON_MULTI_TURN,
            "opponent_policy": OPPONENT_POLICY_ORACLE,
            "information_mode": INFORMATION_ORACLE,
            "same_turn_fallback": fallback,
            "readiness_warning": (
                "Decision lacks a replay-eligible analysis_state_json snapshot."
                if status in (STATUS_NO_SNAPSHOT, STATUS_UNSUPPORTED)
                else None
            ),
        })

    analysis_state = json_load(snap.get("analysis_state_json"))
    if not isinstance(analysis_state, dict):
        return _persist(STATUS_NO_SNAPSHOT, {"ok": False, "error": STATUS_NO_SNAPSHOT})

    seat = int((bundle.get("search_decision") or {}).get("my_player_index") or 0)
    dec = bundle.get("search_decision") or {}
    played = next((c for c in bundle["candidates"] if c.get("chosen")), None)
    if played is None and dec.get("chosen_line_id"):
        played = next(
            (c for c in bundle["candidates"] if c.get("line_id") == dec.get("chosen_line_id")),
            None,
        )

    profile_path = ""
    tmp_profile: Optional[Path] = None
    parsed_profile = None
    if isinstance(profile_json, dict):
        parsed_profile = profile_json
    elif isinstance(profile_json, str) and profile_json.strip():
        try:
            loaded = json.loads(profile_json)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            parsed_profile = loaded
    if parsed_profile is not None:
        tmp_profile = write_temp_json(parsed_profile, suffix="-profile.json")
        profile_path = str(tmp_profile)

    factory = host_factory or cf.open_counterfactual_host
    try:
        # Optional same-turn offline search to enrich alternative roots.
        offline_lines: list[dict] = []
        with factory(
            analysis_state=analysis_state,
            seat=seat,
            expected_hash=expected_hash,
            profile_path=profile_path,
            hold_ms=max(180000, budget.global_time_ms + 60000),
        ) as host:
            restored_hash = str((host.payload or {}).get("root_state_hash") or "")
            if expected_hash and restored_hash and restored_hash != expected_hash:
                return _persist(STATUS_HASH_MISMATCH, {
                    "ok": False,
                    "error": STATUS_HASH_MISMATCH,
                    "root_state_hash": restored_hash,
                    "expected_hash": expected_hash,
                })
            try:
                offline_search = cf.run_offline_search(
                    budget={
                        "node_budget": min(2000, budget.per_turn_node_budget * 3),
                        "time_budget_ms": min(5000, budget.per_turn_time_budget_ms * 4),
                        "max_depth": budget.per_turn_max_depth,
                        "top_n": max(16, budget.root_alt_cap * 4),
                    },
                    overlay=overlay,
                    profile_path=profile_path,
                    seat=seat,
                )
                offline_lines = normalize_engine_lines(offline_search)
            except Exception:
                offline_lines = []

            roots = diversify_roots(
                played=played,
                original=bundle.get("candidates") or [],
                offline=offline_lines,
                root_alt_cap=budget.root_alt_cap,
            )
            if not roots:
                roots = [{
                    "line_id": "played",
                    "moves": packs.canonical_moves((played or {}).get("moves")),
                    "source": "played",
                    "is_played": True,
                }]

            engine_payload = run_offline_rollout(
                roots=roots,
                future_player_turns=turns,
                budget=budget,
                overlay=overlay,
                profile_path=profile_path,
                seat=seat,
                until_turn_number=until_turn or None,
            )
            paths = normalize_engine_lines(engine_payload)
            tree = engine_payload.get("rollout_tree") or {
                "nodes": [],
                "paths": paths,
                "checkpoints": [],
            }
            tiers = outcome_tiers.classify_all_roots(
                roots=roots,
                paths=paths,
                target=tgt,
                seat=seat,
                opponent_top_n=budget.opponent_top_n,
            )
            exploration = outcome_tiers.battlefield_exploration(paths, seat=seat)
            historical = {
                "winner_index": (bundle.get("game") or {}).get("winner_index"),
                "p0_score": (bundle.get("game") or {}).get("p0_score"),
                "p1_score": (bundle.get("game") or {}).get("p1_score"),
                "game_outcome": (bundle.get("search_decision") or {}).get("game_outcome"),
            }
            result = RolloutResult(
                ok=True,
                horizon=HORIZON_MULTI_TURN,
                opponent_policy=OPPONENT_POLICY_ORACLE,
                information_mode=INFORMATION_ORACLE,
                root_state_hash=restored_hash or expected_hash,
                candidate_lines=paths,
                search_stats=engine_payload.get("search_stats") or {},
                assumptions=assumptions,
                result_schema_version=RESULT_SCHEMA_V2,
                run_kind="outcome_rollout",
                future_player_turns=turns,
                rollout_tree=tree,
                outcome_tiers=tiers,
                truncated=bool(engine_payload.get("truncated")),
                stop_reason=str(engine_payload.get("stop_reason") or ""),
            ).to_dict()
            result["roots"] = roots
            result["target"] = tgt
            result["battlefield_exploration"] = exploration
            result["historical_outcome"] = historical
            result["preset"] = preset
            return _persist(STATUS_OK, result)
    except Exception as exc:
        fallback = None
        if include_same_turn:
            try:
                fallback = cf.analyze_same_turn_decision(
                    memory,
                    game_id=game_id,
                    turn=turn,
                    decision_index=decision_index,
                    persist=False,
                    host_factory=host_factory,
                    bundle=bundle,
                )
            except Exception as fallback_exc:
                fallback = {"ok": False, "error": str(fallback_exc)}
        return _persist(STATUS_ENGINE_ERROR, {
            "ok": False,
            "error": STATUS_ENGINE_ERROR,
            "detail": str(exc),
            "horizon": HORIZON_MULTI_TURN,
            "opponent_policy": OPPONENT_POLICY_ORACLE,
            "information_mode": INFORMATION_ORACLE,
            "same_turn_fallback": fallback,
        })
    finally:
        if tmp_profile is not None:
            try:
                tmp_profile.unlink()
            except OSError:
                pass


def render_markdown(result: dict) -> str:
    lines = [
        f"# Outcome Rollout {result.get('game_id')} t{result.get('turn')} d{result.get('decision_index')}",
        "",
        f"- status: `{result.get('status')}`",
        f"- run_kind: `{result.get('run_kind', 'outcome_rollout')}`",
        f"- horizon: `{result.get('horizon')}` ({result.get('future_player_turns')} future player-turns)",
        f"- opponent_policy: `{result.get('opponent_policy')}`",
        f"- information_mode: `{result.get('information_mode')}`",
        f"- truncated: `{result.get('truncated')}` stop=`{result.get('stop_reason')}`",
        f"- root_hash: `{result.get('root_state_hash', '')}`",
    ]
    if result.get("readiness_warning"):
        lines.append(f"- readiness_warning: {result['readiness_warning']}")
    if result.get("error"):
        lines.append(f"- error: {result.get('error')}")
        if result.get("detail"):
            lines.append(f"- detail: {result.get('detail')}")
    tgt = result.get("target") or {}
    lines.append(f"- target: `{tgt}`")
    hist = result.get("historical_outcome") or {}
    if hist:
        lines.append(f"- historical_outcome: `{hist}`")
    lines.append("")
    tiers = result.get("outcome_tiers") or {}
    lines.append("## Outcome tiers by root")
    for row in tiers.get("by_root") or []:
        flags = []
        if row.get("possible"):
            flags.append("possible")
        if row.get("policy_likely"):
            flags.append("policy_likely")
        if row.get("robust"):
            flags.append("robust")
        flag_s = ",".join(flags) if flags else "none"
        if row.get("objective") == "maximize":
            until = row.get("until_turn") or (result.get("target") or {}).get("until_turn")
            horizon_s = f"until turn {until} ends" if until else f"after T+{row.get('after_player_turns')}"
            lines.append(
                f"- `{row.get('root_line_id')}`: {flag_s} "
                f"{horizon_s} "
                f"policy={row.get('policy_value')} "
                f"({row.get('policy_my_score')}-{row.get('policy_opp_score')}) "
                f"best={row.get('possible_value')} robust={row.get('robust_value')} "
                f"(paths={row.get('success_count')}/{row.get('path_count')})"
            )
        else:
            lines.append(
                f"- `{row.get('root_line_id')}`: {flag_s} "
                f"(successes={row.get('success_count')}/{row.get('path_count')})"
            )
    improved = tiers.get("improved_roots") or []
    if improved:
        lines.append("")
        lines.append(f"**Improved vs played baseline:** {', '.join(improved)}")
    note = (result.get("assumptions") or {}).get("note", "")
    if note:
        lines.append("")
        lines.append(f"> {note}")
    fb = result.get("same_turn_fallback")
    if isinstance(fb, dict) and fb:
        lines.append("")
        lines.append("## Same-turn fallback")
        lines.append(f"- status: `{fb.get('status')}` ok=`{fb.get('ok')}`")
    lines.append("")
    return "\n".join(lines)
