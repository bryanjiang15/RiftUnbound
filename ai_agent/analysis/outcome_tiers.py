"""Deterministic possible / policy_likely / robust outcome tiers for rollouts."""
from __future__ import annotations

from typing import Any, Optional


def _checkpoint_state(path: dict) -> dict:
    cp = path.get("checkpoint") or {}
    if isinstance(cp, dict) and cp.get("search_state"):
        return cp["search_state"]
    return path.get("search_state") or {}


def _controls_battlefield(state: dict, bf_id: str) -> bool:
    bfs = state.get("battlefields") or {}
    bf = bfs.get(bf_id) or {}
    if bf.get("i_control") is True:
        return True
    # Fallback: controller label
    return str(bf.get("controller", "")) in ("me", "0")


def _game_won(state: dict, path: dict, seat: int = 0) -> bool:
    if path.get("terminal_reason") == "game_over" or state.get("game_over"):
        winner = state.get("winner_index")
        if winner is None:
            winner = (path.get("checkpoint") or {}).get("winner_index")
        try:
            return int(winner) == int(seat)
        except (TypeError, ValueError):
            return False
    # Score-based victory proximity at checkpoint
    players = state.get("players") or {}
    me = players.get("me") or {}
    try:
        score = float(me.get("score", 0) or 0)
    except (TypeError, ValueError):
        score = 0.0
    victory = state.get("victory_score")
    if victory is None:
        victory = (state.get("turn") or {}).get("victory_score")
    try:
        vs = int(victory) if victory is not None else 8
    except (TypeError, ValueError):
        vs = 8
    return score >= vs


def is_maximize_target(target: Optional[dict]) -> bool:
    kind = str((target or {}).get("kind") or (target or {}).get("type") or "")
    return kind in (
        "max_score_after_turns",
        "max_score",
        "highest_score",
        "score_after_turns",
    )


def required_player_turns(target: Optional[dict]) -> int:
    if not target:
        return 0
    for key in ("after_player_turns", "after_turns", "at_future_player_turns"):
        if target.get(key) is not None:
            try:
                return max(0, int(target[key]))
            except (TypeError, ValueError):
                return 0
    return 0


def until_turn_number(target: Optional[dict]) -> int:
    """Absolute gs.turn_number that must finish. 0 if unset."""
    if not target:
        return 0
    for key in ("until_turn", "until_turn_number", "end_turn_number"):
        if target.get(key) is not None:
            try:
                return max(0, int(target[key]))
            except (TypeError, ValueError):
                return 0
    return 0


def horizon_player_turns_for_until(
    *,
    current_turn: int,
    until_turn: int,
    hard_cap: int,
) -> int:
    """How many completed player-turns to simulate to finish `until_turn`."""
    try:
        cur = max(1, int(current_turn))
        until = max(cur, int(until_turn))
    except (TypeError, ValueError):
        return 1
    needed = until - cur + 1
    cap = max(1, int(hard_cap))
    return max(1, min(needed, cap))


def _checkpoint_turn_number(path: dict) -> Optional[int]:
    cp = path.get("checkpoint") or {}
    if isinstance(cp, dict) and cp.get("turn_number") is not None:
        try:
            return int(cp["turn_number"])
        except (TypeError, ValueError):
            pass
    if path.get("turn_number") is not None:
        try:
            return int(path["turn_number"])
        except (TypeError, ValueError):
            pass
    state = _checkpoint_state(path)
    for key in ("turn_number",):
        if state.get(key) is not None:
            try:
                return int(state[key])
            except (TypeError, ValueError):
                pass
    turn = state.get("turn") or {}
    if isinstance(turn, dict) and turn.get("turn_number") is not None:
        try:
            return int(turn["turn_number"])
        except (TypeError, ValueError):
            pass
    return None


def _path_reached_depth(path: dict, need: int) -> bool:
    if need <= 0:
        return True
    try:
        depth = int(path.get("depth_player_turns", -1) or -1)
    except (TypeError, ValueError):
        depth = -1
    if depth >= need:
        return True
    cp = path.get("checkpoint") or {}
    try:
        return int(cp.get("depth_player_turns", -1) or -1) >= need
    except (TypeError, ValueError):
        return False


def _path_finished_until_turn(path: dict, until: int) -> bool:
    """True once game-turn `until` has ended (next turn has started, or game over)."""
    if until <= 0:
        return True
    state = _checkpoint_state(path)
    if path.get("terminal_reason") == "game_over" or state.get("game_over"):
        return True
    tn = _checkpoint_turn_number(path)
    if tn is None:
        return False
    return tn > until


def _game_scores(path: dict) -> tuple[float, float]:
    """Analyzed-seat points and opponent points at the path checkpoint/leaf."""
    state = _checkpoint_state(path)
    players = state.get("players") or {}
    me = players.get("me") or {}
    opp = players.get("opponent") or {}
    try:
        my = float(me.get("score", state.get("my_score", 0)) or 0)
    except (TypeError, ValueError):
        my = 0.0
    try:
        opp_s = float(opp.get("score", state.get("opp_score", 0)) or 0)
    except (TypeError, ValueError):
        opp_s = 0.0
    return my, opp_s


def path_objective_value(
    path: dict,
    target: dict,
    *,
    seat: int = 0,
) -> Optional[float]:
    """Numeric objective for maximize targets, or None if the path is ineligible."""
    if not is_maximize_target(target):
        return 1.0 if evaluate_target_on_path(path, target, seat=seat) else 0.0
    until = until_turn_number(target)
    if until > 0:
        if not _path_finished_until_turn(path, until):
            return None
    else:
        need = required_player_turns(target)
        if not _path_reached_depth(path, need):
            return None
    my, opp = _game_scores(path)
    metric = str((target or {}).get("metric") or "position")
    if metric in ("score_diff", "lead", "score_lead"):
        return my - opp
    if metric in ("my_score", "vp", "points"):
        return my
    # Default: scoring-profile position (both boards, VP, might, control).
    try:
        pos = path.get("score")
        if pos is not None:
            return float(pos)
    except (TypeError, ValueError):
        pass
    return my - opp


def evaluate_target_on_path(
    path: dict,
    target: dict,
    *,
    seat: int = 0,
) -> bool:
    """Return True if path satisfies the analysis target at its leaf/checkpoint."""
    if is_maximize_target(target):
        return path_objective_value(path, target, seat=seat) is not None
    state = _checkpoint_state(path)
    kind = str((target or {}).get("kind") or (target or {}).get("type") or "win")
    if kind in ("win", "game_won", "win_game"):
        return _game_won(state, path, seat=seat)
    if kind in ("control_battlefield", "controls_battlefield", "battlefield"):
        bf_id = str(target.get("battlefield_id") or target.get("target") or "")
        if not bf_id:
            return False
        # Optional checkpoint depth filter
        want_depth = target.get("at_future_player_turns")
        if want_depth is not None:
            try:
                if int(path.get("depth_player_turns", -1)) < int(want_depth):
                    return False
            except (TypeError, ValueError):
                pass
        return _controls_battlefield(state, bf_id)
    if kind == "score_at_least":
        try:
            threshold = float(target.get("threshold", 8))
        except (TypeError, ValueError):
            threshold = 8.0
        players = state.get("players") or {}
        me = players.get("me") or {}
        try:
            return float(me.get("score", 0) or 0) >= threshold
        except (TypeError, ValueError):
            return False
    return False


def _rank1_segments(path: dict) -> bool:
    """True when every post-root segment is that seat's TurnSearch rank-1 line.

    Root may be an analyst-chosen alternative. Subsequent seats must be ``line-1``
    (TurnSearch labels its best complete line that way). Missing ids do not count
    as rank-1 — otherwise cooperative skip PVs would masquerade as policy.
    """
    segs = path.get("path_segments") or []
    if not segs:
        return False
    for i, seg in enumerate(segs):
        if i == 0 and str(seg.get("kind", "")) == "root":
            continue
        if str(seg.get("line_id", "")) != "line-1":
            return False
    return True


def classify_tiers_for_root(
    *,
    root_line_id: str,
    paths: list[dict],
    target: dict,
    seat: int = 0,
    opponent_top_n: int = 3,
) -> dict[str, Any]:
    """Classify possible / policy_likely / robust for one root alternative."""
    root_paths = [p for p in paths if str(p.get("root_line_id", "")) == str(root_line_id)]
    if not root_paths:
        root_paths = list(paths)

    successes = [p for p in root_paths if evaluate_target_on_path(p, target, seat=seat)]
    possible = bool(successes)

    # Policy PV: both seats' rank-1 replies. Prefer engine `is_policy_pv` when
    # present; do not pick the highest analyzed-seat score (that is cooperative).
    rank1 = [p for p in root_paths if p.get("is_policy_pv") or _rank1_segments(p)]
    rank1 = sorted(
        rank1,
        key=lambda p: (
            int(p.get("opp_policy_rank") or 99),
            int(p.get("our_policy_rank") or 99),
        ),
    )
    policy_path = rank1[0] if rank1 else None
    policy_likely = policy_path is not None and evaluate_target_on_path(
        policy_path, target, seat=seat
    )
    maximize = is_maximize_target(target)

    # Robust: win against every retained first opponent reply. A single
    # cooperative group is not robust when we asked for multiple replies.
    opp_groups: dict[str, list[dict]] = {}
    for p in root_paths:
        segs = p.get("path_segments") or []
        key = "none"
        for i, seg in enumerate(segs):
            if i == 0 and str(seg.get("kind", "")) == "root":
                continue
            if int(seg.get("seat", seat)) == int(seat):
                continue
            key = "|".join(str(m) for m in (seg.get("moves") or [])[:3]) or str(
                seg.get("line_id", "opp")
            )
            break
        opp_groups.setdefault(key, []).append(p)

    robust = False
    if opp_groups:
        all_hit = all(
            any(evaluate_target_on_path(p, target, seat=seat) for p in group)
            for group in opp_groups.values()
        )
        enough_groups = len(opp_groups) >= min(2, max(1, int(opponent_top_n or 1)))
        robust = all_hit and enough_groups

    successes_by_score = sorted(
        successes, key=lambda p: float(p.get("score", 0.0) or 0.0), reverse=True
    )
    representative = {
        "possible": (successes_by_score[0] if successes_by_score else None),
        "policy_pv": policy_path,
        "policy_likely": (policy_path if policy_likely else None),
        "robust": (successes_by_score[0] if robust and successes_by_score else None),
    }

    policy_value: Optional[float] = None
    possible_value: Optional[float] = None
    robust_value: Optional[float] = None
    policy_scores: Optional[tuple[float, float]] = None
    if maximize:
        valued: list[tuple[float, dict]] = []
        for p in root_paths:
            val = path_objective_value(p, target, seat=seat)
            if val is not None:
                valued.append((val, p))
        if valued:
            possible_value, possible_path = max(valued, key=lambda t: t[0])
            representative["possible"] = possible_path
        if policy_path is not None:
            policy_value = path_objective_value(policy_path, target, seat=seat)
            policy_scores = _game_scores(policy_path)
            representative["policy_pv"] = policy_path
            representative["policy_likely"] = policy_path
        group_bests: list[tuple[float, dict]] = []
        for group in opp_groups.values():
            gvals = [
                (path_objective_value(p, target, seat=seat), p)
                for p in group
            ]
            gvals = [(v, p) for v, p in gvals if v is not None]
            if gvals:
                group_bests.append(max(gvals, key=lambda t: t[0]))
        if group_bests:
            robust_value, robust_path = min(group_bests, key=lambda t: t[0])
            representative["robust"] = robust_path
        # Booleans are filled in classify_all_roots vs the played baseline.
        possible = possible_value is not None
        policy_likely = False
        robust = False

    # Serialize without huge blobs
    def _brief(p: Optional[dict]) -> Optional[dict]:
        if not p:
            return None
        my, opp = _game_scores(p)
        out = {
            "line_id": p.get("line_id"),
            "root_line_id": p.get("root_line_id"),
            "moves": p.get("moves"),
            "score": p.get("score"),
            "depth_player_turns": p.get("depth_player_turns"),
            "terminal_reason": p.get("terminal_reason"),
            "path_segments": p.get("path_segments"),
            "checkpoint": p.get("checkpoint"),
            "my_score": my,
            "opp_score": opp,
        }
        obj = path_objective_value(p, target, seat=seat)
        if obj is not None:
            out["objective_value"] = obj
        return out

    return {
        "root_line_id": root_line_id,
        "target": target,
        "possible": possible,
        "policy_likely": policy_likely,
        "robust": robust,
        "success_count": len(successes),
        "path_count": len(root_paths),
        "opponent_groups": len(opp_groups),
        "objective": "maximize" if maximize else "satisfy",
        "policy_value": policy_value,
        "possible_value": possible_value,
        "robust_value": robust_value,
        "policy_my_score": (policy_scores[0] if policy_scores else None),
        "policy_opp_score": (policy_scores[1] if policy_scores else None),
        "after_player_turns": required_player_turns(target),
        "until_turn": until_turn_number(target),
        "representative_paths": {k: _brief(v) for k, v in representative.items()},
    }


def classify_all_roots(
    *,
    roots: list[dict],
    paths: list[dict],
    target: dict,
    seat: int = 0,
    opponent_top_n: int = 3,
) -> dict[str, Any]:
    by_root: list[dict[str, Any]] = []
    for root in roots:
        rid = str(root.get("line_id", ""))
        by_root.append(
            classify_tiers_for_root(
                root_line_id=rid,
                paths=paths,
                target=target,
                seat=seat,
                opponent_top_n=opponent_top_n,
            )
        )
    played = next((r for r in by_root if any(
        str(rt.get("line_id")) == r["root_line_id"] and rt.get("is_played")
        for rt in roots
    )), None)
    alts = [r for r in by_root if played is None or r["root_line_id"] != played["root_line_id"]]
    if is_maximize_target(target) and played is not None:
        played_policy = played.get("policy_value")
        try:
            played_policy_f = float(played_policy) if played_policy is not None else None
        except (TypeError, ValueError):
            played_policy_f = None
        for r in by_root:
            if r["root_line_id"] == played["root_line_id"]:
                r["possible"] = False
                r["policy_likely"] = False
                r["robust"] = False
                continue
            if played_policy_f is None:
                continue
            try:
                pv = float(r["policy_value"]) if r.get("policy_value") is not None else None
                best = float(r["possible_value"]) if r.get("possible_value") is not None else None
                rob = float(r["robust_value"]) if r.get("robust_value") is not None else None
            except (TypeError, ValueError):
                continue
            r["policy_likely"] = pv is not None and pv > played_policy_f
            r["possible"] = best is not None and best > played_policy_f
            r["robust"] = rob is not None and rob > played_policy_f
    # Headline "improved" is policy-likely only. A possible-only win means the
    # opponent has to play a weaker retained reply.
    improved = [
        r for r in alts
        if r.get("policy_likely") and not (played and played.get("policy_likely"))
    ]
    possible_improved = [
        r for r in alts
        if r.get("possible") and not (played and played.get("possible"))
    ]
    return {
        "target": target,
        "by_root": by_root,
        "played": played,
        "improved_roots": [r["root_line_id"] for r in improved],
        "possible_only_roots": [
            r["root_line_id"]
            for r in possible_improved
            if r["root_line_id"] not in {x["root_line_id"] for x in improved}
        ],
        "any_possible_improvement": bool(possible_improved),
        "any_policy_likely_improvement": any(
            r.get("policy_likely") and not (played and played.get("policy_likely"))
            for r in alts
        ),
        "any_robust_improvement": any(
            r.get("robust") and not (played and played.get("robust"))
            for r in alts
        ),
    }


def battlefield_exploration(paths: list[dict], seat: int = 0) -> list[dict[str, Any]]:
    """For UI exploration: which battlefields are controlled on any leaf."""
    found: dict[str, bool] = {}
    for path in paths:
        state = _checkpoint_state(path)
        for bf_id, bf in (state.get("battlefields") or {}).items():
            if _controls_battlefield(state, str(bf_id)):
                found[str(bf_id)] = True
            elif str(bf_id) not in found:
                found[str(bf_id)] = False
    return [{"battlefield_id": k, "controlled_on_some_path": v} for k, v in sorted(found.items())]
