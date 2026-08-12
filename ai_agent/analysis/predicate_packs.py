"""Deterministic, versioned predicate packs for offline same-turn counterfactual.

No LLM. Packs emit ``PredicateClause`` dicts consumed by ``search_metrics``.
"""
from __future__ import annotations

from typing import Any, Optional

from ..search_metrics import evaluate_clause

PREDICATE_PACK_VERSION = "1"

PASS_ONLY_COMMANDS = frozenset({"pass", "end turn", "end_turn"})


def _clause(
    metric: str,
    *,
    comparator: str = ">=",
    threshold: float = 1.0,
    target: Optional[str] = None,
    label: str = "",
    weight: str = "high",
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "metric": metric,
        "comparator": comparator,
        "threshold": threshold,
        "weight": weight,
        "label": label or metric,
    }
    if target is not None:
        out["target"] = target
    return out


def _victory_score(root_search_state: dict, fallback: int = 8) -> int:
    # Brief / snapshot victory is not always on search_state; callers may pass it.
    vs = root_search_state.get("victory_score")
    if vs is None:
        vs = (root_search_state.get("turn") or {}).get("victory_score")
    try:
        return max(1, int(vs if vs is not None else fallback))
    except (TypeError, ValueError):
        return fallback


def _my_score(state: dict) -> float:
    return float((state.get("players") or {}).get("me", {}).get("score", 0) or 0)


def _controlled_bfs(state: dict) -> set[str]:
    out: set[str] = set()
    for bf_id, bf in (state.get("battlefields") or {}).items():
        if bf.get("i_control"):
            out.add(str(bf_id))
    return out


def _enemy_units(state: dict) -> list[str]:
    return [
        inst_id
        for inst_id, u in (state.get("units") or {}).items()
        if str(u.get("owner", "")) == "opponent"
    ]


def _friendly_units(state: dict) -> list[str]:
    return [
        inst_id
        for inst_id, u in (state.get("units") or {}).items()
        if str(u.get("owner", "")) == "me"
    ]


def _uncontrolled_or_opp_bfs(state: dict) -> list[str]:
    out: list[str] = []
    for bf_id, bf in (state.get("battlefields") or {}).items():
        if not bf.get("i_control"):
            out.append(str(bf_id))
    return out


def build_root_search_state(
    *,
    brief_state: Optional[dict] = None,
    snapshot_scalars: Optional[dict] = None,
    search_state: Optional[dict] = None,
) -> dict[str, Any]:
    """Best-effort root search_state for pack generation when only BriefState exists.

    Offline CF prefers a real engine search_state. This projection is only used
    to *generate* predicates (which BFs / units to name), not to score lines.
    """
    if search_state:
        return search_state
    brief = brief_state or {}
    scalars = snapshot_scalars or {}
    my_index = int(brief.get("my_player_index", 0) or 0)
    units: dict[str, Any] = {}
    battlefields: dict[str, Any] = {}
    for u in brief.get("my_base_units") or []:
        if isinstance(u, dict) and u.get("instance_id"):
            units[str(u["instance_id"])] = {
                "owner": "me",
                "might": u.get("current_might", 0),
                "damage": u.get("damage", 0),
                "health": max(0, int(u.get("current_might", 0) or 0) - int(u.get("damage", 0) or 0)),
                "battlefield": None,
            }
    for bf in brief.get("battlefields") or []:
        if not isinstance(bf, dict):
            continue
        bf_id = str(bf.get("battlefield_id", ""))
        ctrl = int(bf.get("controller_index", -1) if bf.get("controller_index") is not None else -1)
        battlefields[bf_id] = {
            "i_control": ctrl == my_index,
            "controller": "me" if ctrl == my_index else ("opponent" if ctrl >= 0 else None),
            "my_might": 0,
            "opp_might": 0,
            "my_units": 0,
            "opp_units": 0,
        }
        for u in bf.get("my_units") or []:
            if isinstance(u, dict) and u.get("instance_id"):
                units[str(u["instance_id"])] = {
                    "owner": "me",
                    "might": u.get("current_might", 0),
                    "damage": u.get("damage", 0),
                    "health": max(0, int(u.get("current_might", 0) or 0) - int(u.get("damage", 0) or 0)),
                    "battlefield": bf_id,
                }
                battlefields[bf_id]["my_units"] += 1
                battlefields[bf_id]["my_might"] += int(u.get("current_might", 0) or 0)
        for u in bf.get("opponent_units") or []:
            if isinstance(u, dict) and u.get("instance_id"):
                units[str(u["instance_id"])] = {
                    "owner": "opponent",
                    "might": u.get("current_might", 0),
                    "damage": u.get("damage", 0),
                    "health": max(0, int(u.get("current_might", 0) or 0) - int(u.get("damage", 0) or 0)),
                    "battlefield": bf_id,
                }
                battlefields[bf_id]["opp_units"] += 1
                battlefields[bf_id]["opp_might"] += int(u.get("current_might", 0) or 0)
    my_score = brief.get("my_score", scalars.get("my_score", 0))
    opp_score = brief.get("opponent_score", scalars.get("opp_score", 0))
    return {
        "units": units,
        "battlefields": battlefields,
        "players": {
            "me": {
                "score": my_score or 0,
                "cards_in_hand": len(brief.get("my_hand") or []),
                "ready_runes": scalars.get("my_ready_rune_count", 0) or 0,
            },
            "opponent": {
                "score": opp_score or 0,
                "cards_in_hand": brief.get("opponent_hand_size", 0) or 0,
                "ready_runes": 0,
            },
        },
        "turn": {"points_scored": 0, "enemy_units_killed": 0, "battlefields_conquered": 0},
        "cards_played": [],
        "victory_score": brief.get("victory_score", 8) or 8,
    }


def pack_win_now(root: dict, *, victory_score: Optional[int] = None) -> dict[str, Any]:
    vs = victory_score if victory_score is not None else _victory_score(root)
    return {
        "id": "win_now",
        "combine": "all",
        "constraints": [
            _clause("score", target="me", comparator=">=", threshold=float(vs), label="win_now"),
        ],
    }


def pack_score_more(root: dict, *, played_score: Optional[float] = None) -> dict[str, Any]:
    base = played_score if played_score is not None else _my_score(root)
    return {
        "id": "score_more",
        "combine": "all",
        "constraints": [
            _clause(
                "score",
                target="me",
                comparator=">=",
                threshold=float(base) + 1.0,
                label="score_more_than_played",
            ),
        ],
    }


def pack_conquer_progress(root: dict, *, battlefield_id: Optional[str] = None) -> list[dict[str, Any]]:
    targets = [battlefield_id] if battlefield_id else _uncontrolled_or_opp_bfs(root)
    packs: list[dict[str, Any]] = []
    for bf_id in targets:
        packs.append({
            "id": f"conquer_progress:{bf_id}",
            "combine": "all",
            "constraints": [
                _clause(
                    "i_control_battlefield",
                    target=bf_id,
                    comparator=">=",
                    threshold=1.0,
                    label=f"conquer_{bf_id}",
                ),
            ],
        })
    return packs


def pack_remove_threat(root: dict, *, unit_id: Optional[str] = None) -> list[dict[str, Any]]:
    targets = [unit_id] if unit_id else _enemy_units(root)
    packs: list[dict[str, Any]] = []
    for uid in targets:
        packs.append({
            "id": f"remove_threat:{uid}",
            "combine": "all",
            "constraints": [
                _clause(
                    "unit_alive",
                    target=uid,
                    comparator="<=",
                    threshold=0.0,
                    label=f"kill_{uid}",
                ),
            ],
        })
    return packs


def pack_preserve_with_progress(
    root: dict,
    *,
    unit_id: Optional[str] = None,
    played_score: Optional[float] = None,
) -> list[dict[str, Any]]:
    """Keep a named friendly unit alive AND match/improve score or control vs played/root."""
    targets = [unit_id] if unit_id else _friendly_units(root)
    base_score = played_score if played_score is not None else _my_score(root)
    root_ctrl = _controlled_bfs(root)
    packs: list[dict[str, Any]] = []
    for uid in targets:
        constraints = [
            _clause("unit_alive", target=uid, comparator=">=", threshold=1.0, label=f"preserve_{uid}"),
            _clause(
                "score",
                target="me",
                comparator=">=",
                threshold=float(base_score),
                label="match_or_beat_score",
            ),
        ]
        # If we already control a BF, require keeping at least one; otherwise require a conquer.
        if root_ctrl:
            bf_id = sorted(root_ctrl)[0]
            constraints.append(
                _clause(
                    "i_control_battlefield",
                    target=bf_id,
                    comparator=">=",
                    threshold=1.0,
                    label=f"keep_control_{bf_id}",
                )
            )
        else:
            bfs = _uncontrolled_or_opp_bfs(root)
            if bfs:
                constraints.append(
                    _clause(
                        "i_control_battlefield",
                        target=bfs[0],
                        comparator=">=",
                        threshold=1.0,
                        label=f"gain_control_{bfs[0]}",
                    )
                )
        packs.append({
            "id": f"preserve_with_progress:{uid}",
            "combine": "all",
            "constraints": constraints,
        })
    return packs


_STATE_TARGET_TO_CLAUSE = {
    "my_score": ("score", "me"),
    "my_ready_runes": ("ready_runes", "me"),
    "points_scored": ("points_scored", None),
    "enemy_units_killed": ("enemy_units_killed", None),
    "battlefields_conquered": ("battlefields_conquered", None),
    "cards_in_hand_net": ("cards_in_hand", "me"),
}


def pack_logged_goal(goal_set: Optional[dict]) -> list[dict[str, Any]]:
    """Translate compatible persisted GoalSet state_targets into PredicateClauses."""
    if not goal_set:
        return []
    goals = goal_set.get("goals") if isinstance(goal_set, dict) else None
    if not isinstance(goals, list):
        return []
    packs: list[dict[str, Any]] = []
    for goal in goals:
        if not isinstance(goal, dict):
            continue
        kind = str(goal.get("kind", ""))
        if kind != "state_target":
            continue
        metric = str(goal.get("metric", ""))
        mapped = _STATE_TARGET_TO_CLAUSE.get(metric)
        if mapped is None:
            continue
        search_metric, target = mapped
        comparator = str(goal.get("comparator", ">=") or ">=")
        try:
            threshold = float(goal.get("threshold", 0) or 0)
        except (TypeError, ValueError):
            continue
        gid = str(goal.get("id", metric))
        packs.append({
            "id": f"logged_goal:{gid}",
            "combine": "all",
            "constraints": [
                _clause(
                    search_metric,
                    target=target,
                    comparator=comparator,
                    threshold=threshold,
                    label=f"goal_{gid}",
                ),
            ],
        })
    return packs


def all_packs(
    root: dict,
    *,
    played_score: Optional[float] = None,
    victory_score: Optional[int] = None,
    goal_set: Optional[dict] = None,
) -> list[dict[str, Any]]:
    packs: list[dict[str, Any]] = [
        pack_win_now(root, victory_score=victory_score),
        pack_score_more(root, played_score=played_score),
    ]
    packs.extend(pack_conquer_progress(root))
    packs.extend(pack_remove_threat(root))
    packs.extend(pack_preserve_with_progress(root, played_score=played_score))
    packs.extend(pack_logged_goal(goal_set))
    return packs


def canonical_moves(moves: Any) -> list[str]:
    out: list[str] = []
    for m in moves or []:
        if isinstance(m, str):
            cmd = m.strip()
        elif isinstance(m, dict):
            cmd = str(m.get("command") or m.get("raw_command") or "").strip()
            if not cmd and m.get("action"):
                action = str(m.get("action"))
                cmd = "end turn" if action == "end_turn" else action.replace("_", " ")
        else:
            cmd = str(m).strip()
        if cmd:
            out.append(cmd)
    return out


def is_pass_only(moves: Any) -> bool:
    cmds = [c.lower() for c in canonical_moves(moves)]
    if not cmds:
        return True
    return all(c in PASS_ONLY_COMMANDS for c in cmds)


def _metric_improved(root: dict, leaf: dict, pack: dict) -> bool:
    """True if at least one objective-relevant metric improved vs root."""
    for clause in pack.get("constraints") or []:
        root_res = evaluate_clause(clause, root)
        leaf_res = evaluate_clause(clause, leaf)
        if not root_res.get("supported") or not leaf_res.get("supported"):
            continue
        try:
            rv = float(root_res.get("value", 0) or 0)
            lv = float(leaf_res.get("value", 0) or 0)
        except (TypeError, ValueError):
            continue
        comp = str(clause.get("comparator", ">="))
        if comp in (">=", "==") and lv > rv + 1e-9:
            return True
        if comp == "<=" and lv < rv - 1e-9:
            return True
        if leaf_res.get("met") and not root_res.get("met"):
            return True
    return False


def is_terminal_win(leaf: dict, victory_score: int) -> bool:
    if bool((leaf or {}).get("game_over")) and int((leaf or {}).get("winner_index", -1)) >= 0:
        return True
    players = (leaf or {}).get("players") or {}
    try:
        return float((players.get("me") or {}).get("score", 0) or 0) >= float(victory_score)
    except (TypeError, ValueError):
        return False


def eligibility_guard(
    line: dict,
    *,
    root_state: dict,
    pack: dict,
    victory_score: int = 8,
) -> dict[str, Any]:
    """Reject fake defensive successes: pass-only non-terminal lines cannot improve.

    Non-terminal matches must contain a non-pass action and improve an
    objective-relevant metric from the root. V1 does not claim a battlefield or
    unit survives the opponent's next turn.
    """
    leaf = line.get("search_state") or {}
    terminal = is_terminal_win(leaf, victory_score) or bool(
        (line.get("resolved_state") or {}).get("wins_game")
    )
    pass_only = is_pass_only(line.get("moves"))
    if terminal:
        return {"eligible": True, "reason": "terminal_win", "pass_only": pass_only}
    if pass_only:
        return {
            "eligible": False,
            "reason": "pass_only_non_terminal",
            "pass_only": True,
        }
    if not _metric_improved(root_state, leaf, pack):
        return {
            "eligible": False,
            "reason": "no_objective_progress",
            "pass_only": False,
        }
    return {"eligible": True, "reason": "progress", "pass_only": False}
