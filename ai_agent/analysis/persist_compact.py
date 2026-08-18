"""Compact Analysis-run payloads before SQLite persist.

Full outcome rollouts include rollout_tree.nodes / every leaf candidate_line and
per-ply search_state. The Analysis UI only needs outcome_tiers representative
paths (moves + path_segments) and same-turn comparison packs. LineReplayer
rebuilds board states from commands.
"""
from __future__ import annotations

from typing import Any, Optional

STORAGE_MARK = "compact_v1"

_KEEP_TOP = (
    "ok",
    "status",
    "error",
    "detail",
    "horizon",
    "opponent_policy",
    "information_mode",
    "root_state_hash",
    "search_stats",
    "assumptions",
    "result_schema_version",
    "run_kind",
    "future_player_turns",
    "truncated",
    "stop_reason",
    "outcome_tiers",
    "roots",
    "target",
    "battlefield_exploration",
    "historical_outcome",
    "preset",
    "game_id",
    "turn",
    "decision_index",
    "comparison",
    "base_profile_line_count",
    "goals_source",
    "readiness_warning",
    "predicate_pack_version",
    "same_turn_fallback",
)

_LINE_KEEP = (
    "line_id",
    "root_line_id",
    "score",
    "moves",
    "canonical_moves",
    "complete",
    "terminal_reason",
    "leaf_hash",
    "source",
    "depth_player_turns",
    "is_played",
    "objective_value",
    "my_score",
    "opp_score",
)

_SEGMENT_KEEP = (
    "kind",
    "seat",
    "moves",
    "score",
    "policy_rank",
    "line_id",
    "boundary",
    "complete",
    "terminal_reason",
    "depth_player_turns",
)

_CHECKPOINT_KEEP = (
    "acting_seat",
    "complete",
    "depth_player_turns",
    "game_over",
    "terminal_reason",
    "turn_number",
    "turn_player_index",
    "winner_index",
)


def _pick(src: dict, keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: src[k] for k in keys if k in src}


def _compact_checkpoint(cp: Any) -> Any:
    if not isinstance(cp, dict):
        return cp
    return _pick(cp, _CHECKPOINT_KEEP)


def _compact_segment(seg: Any) -> Any:
    if not isinstance(seg, dict):
        return seg
    out = _pick(seg, _SEGMENT_KEEP)
    if "checkpoint" in seg:
        out["checkpoint"] = _compact_checkpoint(seg.get("checkpoint"))
    return out


def compact_path(path: Any) -> Any:
    """Keep moves / scores / segments; drop per-ply search_state."""
    if not isinstance(path, dict):
        return path
    out = _pick(path, _LINE_KEEP)
    segs = path.get("path_segments")
    if isinstance(segs, list):
        out["path_segments"] = [_compact_segment(s) for s in segs]
    if "checkpoint" in path:
        out["checkpoint"] = _compact_checkpoint(path.get("checkpoint"))
    return out


def _compact_line(line: Any) -> Any:
    if not isinstance(line, dict):
        return line
    out = compact_path(line)
    return out


def _compact_pack_match(match: Any) -> Any:
    if not isinstance(match, dict):
        return match
    out = dict(match)
    out.pop("source_line", None)
    if "canonical_moves" not in out and "moves" in out:
        out["canonical_moves"] = out.get("moves")
    return out


def _compact_comparison(comparison: Any) -> Any:
    if not isinstance(comparison, dict):
        return comparison
    out: dict[str, Any] = {}
    if "played" in comparison:
        played = comparison.get("played")
        if isinstance(played, dict):
            out["played"] = _pick(
                played, ("line_id", "moves", "score", "leaf_hash")
            )
        else:
            out["played"] = played
    for key in (
        "original_line_count",
        "offline_line_count",
        "assumptions",
        "original_keys",
    ):
        if key in comparison:
            out[key] = comparison[key]
    packs_out = []
    for pack in comparison.get("packs") or []:
        if not isinstance(pack, dict):
            continue
        p = {
            "pack_id": pack.get("pack_id"),
            "constraints": pack.get("constraints"),
            "best_offline_in_original_beam": pack.get("best_offline_in_original_beam"),
            "original_beam_had_hard_match": pack.get("original_beam_had_hard_match"),
            "offline_found_hard_match": pack.get("offline_found_hard_match"),
            "base_found_hard_match": pack.get("base_found_hard_match"),
        }
        for mk in (
            "offline_hard_matches",
            "original_hard_matches",
            "base_profile_hard_matches",
        ):
            raw = pack.get(mk)
            if isinstance(raw, list):
                p[mk] = [_compact_pack_match(m) for m in raw]
        packs_out.append(p)
    if packs_out:
        out["packs"] = packs_out
    return out


def _compact_tiers(tiers: Any) -> Any:
    if not isinstance(tiers, dict):
        return tiers
    out = dict(tiers)
    for key in ("by_root",):
        rows = out.get(key)
        if isinstance(rows, list):
            out[key] = [_compact_tier_row(r) for r in rows]
    if isinstance(out.get("played"), dict):
        out["played"] = _compact_tier_row(out["played"])
    return out


def _compact_tier_row(row: Any) -> Any:
    if not isinstance(row, dict):
        return row
    out = dict(row)
    reps = out.get("representative_paths")
    if isinstance(reps, dict):
        out["representative_paths"] = {
            name: compact_path(path) for name, path in reps.items()
        }
    return out


def compact_result_for_storage(result: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Return a UI-sufficient copy with tree / search_state stripped.

    Idempotent. Same-turn runs keep slim candidate_lines; outcome rollouts drop
    candidate_lines and rollout_tree (representative_paths are enough).
    """
    if not isinstance(result, dict):
        return result
    run_kind = str(result.get("run_kind") or "")
    horizon = str(result.get("horizon") or "")
    out: dict[str, Any] = {k: result[k] for k in _KEEP_TOP if k in result}
    if "outcome_tiers" in out:
        out["outcome_tiers"] = _compact_tiers(out["outcome_tiers"])
    if "roots" in out and isinstance(out["roots"], list):
        out["roots"] = [_compact_line(r) for r in out["roots"]]
    if "comparison" in out:
        out["comparison"] = _compact_comparison(out["comparison"])
    fb = result.get("same_turn_fallback")
    if isinstance(fb, dict):
        out["same_turn_fallback"] = compact_result_for_storage(fb)
    is_rollout = run_kind == "outcome_rollout" or horizon == "multi_turn"
    if not is_rollout:
        lines = result.get("candidate_lines")
        if isinstance(lines, list):
            out["candidate_lines"] = [_compact_line(line) for line in lines]
    out["storage"] = STORAGE_MARK
    return out
