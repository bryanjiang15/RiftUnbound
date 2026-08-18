"""Same-turn offline counterfactual: restore snapshot, search, compare lines."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Optional

from .. import engine_client
from ..eval.godot_host import GodotHost, find_godot
from ..memory import Memory
from ..search_metrics import evaluate_clause
from . import predicate_packs as packs
from .persist_compact import compact_result_for_storage
from .rollout_contracts import (
    HORIZON_ONE_PLAYER_TURN,
    INFORMATION_PUBLIC,
    OPPONENT_POLICY_NONE,
    RolloutResult,
    v1_assumptions,
)

DEFAULT_BUDGET = {
    "node_budget": 2000,
    "time_budget_ms": 5000,
    "max_depth": 12,
    "top_n": 20,
}

CF_SCRIPT = "res://Scripts/Tools/CounterfactualRunner.gd"
STATUS_OK = "ok"
STATUS_UNSUPPORTED = "unsupported_snapshot"
STATUS_HASH_MISMATCH = "hash_mismatch"
STATUS_ENGINE_ERROR = "engine_error"
STATUS_NO_SNAPSHOT = "unsupported_snapshot"


def _json_load(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return None


def _canonical_key(moves: Any, leaf_hash: str = "") -> str:
    cmds = "|".join(packs.canonical_moves(moves))
    return f"{cmds}#{leaf_hash}"


def _leaf_hash(line: dict) -> str:
    state = line.get("search_state") or line.get("resolved_state") or {}
    blob = json.dumps(state, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def load_decision_bundle(
    memory: Memory,
    *,
    game_id: str,
    turn: int,
    decision_index: int,
    candidate_detail: bool = True,
    include_analysis_state: bool = True,
) -> dict[str, Any]:
    """Load search_decision + snapshot + candidates + reasoner + goals for one key.

    ``candidate_detail=False`` skips per-line search_state / features /
    resolved_state JSON — Analysis UI list/detail only needs moves.
    ``include_analysis_state=False`` skips the GameState dump column.
    """
    with memory._connect() as conn:
        dec = conn.execute(
            """
            SELECT * FROM search_decisions
            WHERE game_id=? AND turn=? AND decision_index=?
            ORDER BY id DESC LIMIT 1
            """,
            (game_id, turn, decision_index),
        ).fetchone()
        if include_analysis_state:
            snap = conn.execute(
                """
                SELECT * FROM decision_snapshots
                WHERE game_id=? AND turn=? AND decision_index=?
                ORDER BY id DESC LIMIT 1
                """,
                (game_id, turn, decision_index),
            ).fetchone()
        else:
            snap = conn.execute(
                """
                SELECT id, game_id, turn, decision_index, my_score, opp_score,
                       my_energy, board_might_diff, cards_in_hand, cards_in_hand_opp,
                       bf_control_net, analysis_state_schema_version, root_state_hash,
                       timestamp,
                       (analysis_state_json IS NOT NULL AND analysis_state_json != '')
                         AS has_analysis_state
                FROM decision_snapshots
                WHERE game_id=? AND turn=? AND decision_index=?
                ORDER BY id DESC LIMIT 1
                """,
                (game_id, turn, decision_index),
            ).fetchone()
        reasoner = conn.execute(
            """
            SELECT * FROM reasoner_decisions
            WHERE game_id=? AND turn=? AND decision_index=?
            ORDER BY id DESC LIMIT 1
            """,
            (game_id, turn, decision_index),
        ).fetchone()
        client_metrics = conn.execute(
            """
            SELECT * FROM client_decision_metrics
            WHERE game_id=? AND turn=?
            ORDER BY id DESC LIMIT 1
            """,
            (game_id, turn),
        ).fetchone()
        eval_metrics = conn.execute(
            """
            SELECT * FROM decision_eval_metrics
            WHERE game_id=? AND turn=? AND decision_index=?
            ORDER BY id DESC LIMIT 1
            """,
            (game_id, turn, decision_index),
        ).fetchone()
        weight_row = None
        candidates: list[dict[str, Any]] = []
        if dec is not None:
            if dec["weight_version_id"]:
                weight_sql = (
                    "SELECT id FROM weight_versions WHERE id=?"
                    if not candidate_detail
                    else "SELECT * FROM weight_versions WHERE id=?"
                )
                weight_row = conn.execute(
                    weight_sql,
                    (int(dec["weight_version_id"]),),
                ).fetchone()
            cand_sql = (
                """
                SELECT line_id, rank, score, chosen, moves_json
                FROM candidate_lines
                WHERE search_decision_id=?
                ORDER BY rank ASC
                """
                if not candidate_detail
                else """
                SELECT * FROM candidate_lines
                WHERE search_decision_id=?
                ORDER BY rank ASC
                """
            )
            for row in conn.execute(cand_sql, (int(dec["id"]),)).fetchall():
                item = {
                    "line_id": row["line_id"],
                    "rank": row["rank"],
                    "score": row["score"],
                    "chosen": bool(row["chosen"]),
                    "moves": _json_load(row["moves_json"]) or [],
                }
                if candidate_detail:
                    item["breakdown"] = _json_load(row["breakdown_json"]) or {}
                    item["features"] = _json_load(row["features_json"]) or {}
                    item["resolved_state"] = _json_load(row["resolved_state_json"]) or {}
                    item["search_state"] = _json_load(row["search_state_json"]) or {}
                candidates.append(item)
        game = conn.execute(
            "SELECT * FROM games WHERE game_id=?", (game_id,)
        ).fetchone()

    def _row(r) -> Optional[dict]:
        return dict(r) if r is not None else None

    return {
        "game_id": game_id,
        "turn": turn,
        "decision_index": decision_index,
        "search_decision": _row(dec),
        "snapshot": _row(snap),
        "candidates": candidates,
        "reasoner": _row(reasoner),
        "client_metrics": _row(client_metrics),
        "eval_metrics": _row(eval_metrics),
        "weight_version": _row(weight_row),
        "game": _row(game),
    }


def snapshot_status(bundle: dict) -> str:
    snap = bundle.get("snapshot") or {}
    analysis = snap.get("analysis_state_json")
    if not analysis:
        return STATUS_NO_SNAPSHOT
    payload = _json_load(analysis)
    if not isinstance(payload, dict):
        return STATUS_NO_SNAPSHOT
    replay = payload.get("replay") or {}
    if replay.get("supported") is False:
        return STATUS_UNSUPPORTED
    return STATUS_OK


def reconstruct_profile(bundle: dict) -> tuple[Optional[str], Optional[dict]]:
    """Return (profile_json, overlay) from weight_versions + search_decisions."""
    weight = bundle.get("weight_version") or {}
    profile_json = weight.get("profile_json")
    dec = bundle.get("search_decision") or {}
    overlay = _json_load(dec.get("overlay_json"))
    return profile_json, overlay if isinstance(overlay, dict) else None


def _normalize_engine_lines(payload: dict) -> list[dict[str, Any]]:
    lines = payload.get("candidate_lines") or payload.get("lines") or []
    out: list[dict[str, Any]] = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        moves = line.get("moves") or []
        out.append({
            "line_id": line.get("line_id"),
            "score": line.get("score", 0.0),
            "moves": moves,
            "canonical_moves": packs.canonical_moves(moves),
            "breakdown": line.get("breakdown") or line.get("score_breakdown") or {},
            "features": line.get("features") or {},
            "resolved_state": line.get("resolved_state") or {},
            "search_state": line.get("search_state") or {},
            "complete": bool(line.get("complete", False)),
            "terminal_reason": line.get("terminal_reason", ""),
            "leaf_hash": _leaf_hash(line),
        })
    return out


def evaluate_pack_on_lines(
    pack: dict,
    lines: list[dict],
    *,
    root_state: dict,
    victory_score: int = 8,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    constraints = pack.get("constraints") or []
    for line in lines:
        state = line.get("search_state") or {}
        clause_results = [evaluate_clause(c, state) for c in constraints]
        hard = all(c.get("supported") and c.get("met") for c in clause_results) if clause_results else False
        guard = packs.eligibility_guard(
            line, root_state=root_state, pack=pack, victory_score=victory_score
        )
        if hard and guard["eligible"]:
            matches.append({
                "line_id": line.get("line_id"),
                "canonical_moves": line.get("canonical_moves") or packs.canonical_moves(line.get("moves")),
                "leaf_hash": line.get("leaf_hash") or _leaf_hash(line),
                "score": line.get("score"),
                "clauses": clause_results,
                "eligibility": guard,
                "source_line": line,
            })
    return matches


def compare_lines(
    *,
    played: Optional[dict],
    original: list[dict],
    offline: list[dict],
    offline_base: Optional[list[dict]] = None,
    root_state: dict,
    victory_score: int,
    goal_set: Optional[dict] = None,
    played_score: Optional[float] = None,
) -> dict[str, Any]:
    """Compare played / original beam / offline (+ optional base-profile) lines."""
    original_keys = {
        _canonical_key(l.get("moves"), l.get("leaf_hash") or _leaf_hash(l))
        for l in original
    }
    all_packs = packs.all_packs(
        root_state,
        played_score=played_score,
        victory_score=victory_score,
        goal_set=goal_set,
    )
    pack_results: list[dict[str, Any]] = []
    for pack in all_packs:
        off_matches = evaluate_pack_on_lines(
            pack, offline, root_state=root_state, victory_score=victory_score
        )
        orig_matches = evaluate_pack_on_lines(
            pack, original, root_state=root_state, victory_score=victory_score
        )
        base_matches = evaluate_pack_on_lines(
            pack, offline_base or [], root_state=root_state, victory_score=victory_score
        ) if offline_base is not None else []
        best = off_matches[0] if off_matches else None
        in_original = False
        if best is not None:
            key = _canonical_key(best.get("canonical_moves"), best.get("leaf_hash", ""))
            in_original = any(
                _canonical_key(m.get("canonical_moves"), m.get("leaf_hash", "")) == key
                or (
                    packs.canonical_moves(m.get("canonical_moves") or m.get("moves"))
                    == (best.get("canonical_moves") or [])
                )
                for m in orig_matches
            )
            # Also check full original beam, not only hard-matches.
            if not in_original:
                in_original = any(
                    packs.canonical_moves(l.get("moves")) == (best.get("canonical_moves") or [])
                    for l in original
                )
        pack_results.append({
            "pack_id": pack["id"],
            "constraints": pack["constraints"],
            "offline_hard_matches": [
                {k: v for k, v in m.items() if k != "source_line"} for m in off_matches
            ],
            "original_hard_matches": [
                {k: v for k, v in m.items() if k != "source_line"} for m in orig_matches
            ],
            "base_profile_hard_matches": [
                {k: v for k, v in m.items() if k != "source_line"} for m in base_matches
            ],
            "best_offline_in_original_beam": in_original,
            "original_beam_had_hard_match": bool(orig_matches),
            "offline_found_hard_match": bool(off_matches),
            "base_found_hard_match": bool(base_matches),
        })
    return {
        "played": {
            "line_id": (played or {}).get("line_id"),
            "moves": packs.canonical_moves((played or {}).get("moves")),
            "score": (played or {}).get("score"),
            "leaf_hash": _leaf_hash(played) if played else "",
        },
        "original_line_count": len(original),
        "offline_line_count": len(offline),
        "original_keys": sorted(original_keys),
        "packs": pack_results,
        "assumptions": v1_assumptions(),
    }


def _write_temp_json(obj: Any, suffix: str = ".json") -> Path:
    tmp = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8")
    json.dump(obj, tmp, default=str)
    tmp.close()
    return Path(tmp.name)


def open_counterfactual_host(
    *,
    analysis_state: dict,
    seat: int = 0,
    expected_hash: str = "",
    profile_path: str = "",
    hold_ms: int = 180000,
    ready_timeout_s: float = 90.0,
) -> Any:
    """Spawn CounterfactualRunner in agent_ready mode. Returns GodotHost context manager."""
    from contextlib import contextmanager
    import os
    import subprocess
    import time
    from ..eval import godot_host as gh

    @contextmanager
    def _cm():
        godot = find_godot()
        if godot is None:
            raise RuntimeError("Godot binary not found (set GODOT)")
        state_path = _write_temp_json(analysis_state, suffix="-analysis.json")
        done_file = tempfile.NamedTemporaryFile(prefix="riftbound-cf-done-", delete=False)
        done_path = Path(done_file.name)
        done_file.close()
        if done_path.exists():
            done_path.unlink()
        cmd = [
            godot,
            "--headless",
            "--path",
            str(gh.REPO_ROOT),
            "--script",
            CF_SCRIPT,
            "--",
            "--analysis-state-file",
            str(state_path),
            "--seat",
            str(seat),
            "--mode",
            "agent_ready",
        ]
        if expected_hash:
            cmd.extend(["--expected-hash", expected_hash])
        if profile_path:
            cmd.extend(["--profile-path", profile_path])
        env = os.environ.copy()
        env["RIFTBOUND_EVAL_DONE_PATH"] = str(done_path)
        env["RIFTBOUND_EVAL_HOLD_MS"] = str(hold_ms)
        env.setdefault("RIFTBOUND_ENGINE_PORT", "0")
        proc = subprocess.Popen(
            cmd,
            cwd=str(gh.REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        host = GodotHost(payload={}, process=proc, done_path=done_path)
        try:
            assert proc.stdout is not None
            deadline = time.time() + ready_timeout_s
            payload: Optional[dict[str, Any]] = None
            while time.time() < deadline:
                if proc.poll() is not None:
                    rest = proc.stdout.read()
                    raise RuntimeError(
                        "CounterfactualRunner exited before EVAL_READY\n"
                        f"exit={proc.returncode}\noutput:\n{rest}"
                    )
                line = proc.stdout.readline()
                if not line:
                    time.sleep(0.05)
                    continue
                try:
                    parsed = gh._parse_ready_line(line)
                except json.JSONDecodeError:
                    continue
                if parsed is not None:
                    payload = parsed
                    break
            if payload is None:
                raise RuntimeError("timed out waiting for EVAL_READY from CounterfactualRunner")
            if not payload.get("ok", False):
                raise RuntimeError(f"CounterfactualRunner failed: {payload.get('error', payload)}")
            host.payload = payload
            port = host.engine_port
            if port:
                os.environ["RIFTBOUND_ENGINE_PORT"] = str(port)
            yield host
        finally:
            host.close()
            try:
                state_path.unlink()
            except OSError:
                pass
            if done_path.exists():
                try:
                    done_path.unlink()
                except OSError:
                    pass

    return _cm()


def run_offline_search(
    *,
    budget: Optional[dict] = None,
    overlay: Optional[dict] = None,
    profile_path: str = "",
    seat: Optional[int] = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "mode": "main",
        "budget": dict(DEFAULT_BUDGET if budget is None else {**DEFAULT_BUDGET, **budget}),
        "top_n": int((budget or DEFAULT_BUDGET).get("top_n", DEFAULT_BUDGET["top_n"])),
    }
    if overlay:
        body["overlay"] = overlay
    if profile_path:
        body["profile_path"] = profile_path
    if seat is not None:
        body["seat"] = seat
    timeout = max(8.0, (body["budget"].get("time_budget_ms", 5000) / 1000.0) + 5.0)
    # engine_client.search uses default timeout; bump via env for long CF searches.
    import os
    prev = os.environ.get("RIFTBOUND_ENGINE_TIMEOUT_S")
    os.environ["RIFTBOUND_ENGINE_TIMEOUT_S"] = str(timeout)
    try:
        return engine_client.search(body)
    finally:
        if prev is None:
            os.environ.pop("RIFTBOUND_ENGINE_TIMEOUT_S", None)
        else:
            os.environ["RIFTBOUND_ENGINE_TIMEOUT_S"] = prev


def analyze_same_turn_decision(
    memory: Memory,
    *,
    game_id: str,
    turn: int,
    decision_index: int,
    budget: Optional[dict] = None,
    persist: bool = True,
    host_factory=None,
    bundle: Optional[dict] = None,
) -> dict[str, Any]:
    """Full same-turn counterfactual for one decision. Optionally persist a run row."""
    if bundle is None:
        bundle = load_decision_bundle(memory, game_id=game_id, turn=turn, decision_index=decision_index)
    assumptions = v1_assumptions()
    status = snapshot_status(bundle)
    snap = bundle.get("snapshot") or {}
    expected_hash = str(snap.get("root_state_hash") or "")
    profile_json, overlay = reconstruct_profile(bundle)
    budget_used = dict(DEFAULT_BUDGET if budget is None else {**DEFAULT_BUDGET, **budget})
    search_inputs = {"mode": "main", **budget_used}
    profile_inputs = {
        "weight_version_id": (bundle.get("search_decision") or {}).get("weight_version_id"),
        "has_overlay": bool(overlay),
        "goals_source": (bundle.get("search_decision") or {}).get("goals_source"),
    }

    def _persist(status_val: str, result: dict) -> dict:
        result = {
            **result,
            "status": status_val,
            "game_id": game_id,
            "turn": turn,
            "decision_index": decision_index,
            "assumptions": assumptions,
            "predicate_pack_version": packs.PREDICATE_PACK_VERSION,
            "run_kind": "same_turn",
            "result_schema_version": "1",
        }
        if persist:
            result = compact_result_for_storage(result) or result
            memory.record_counterfactual_run(
                game_id=game_id,
                turn=turn,
                decision_index=decision_index,
                root_state_hash=expected_hash or None,
                predicate_pack_version=packs.PREDICATE_PACK_VERSION,
                search_inputs=search_inputs,
                profile_inputs=profile_inputs,
                budget=budget_used,
                assumptions=assumptions,
                status=status_val,
                result=result,
                run_kind="same_turn",
                result_schema_version="1",
                future_player_turns=0,
                opponent_policy=OPPONENT_POLICY_NONE,
            )
        return result

    if status != STATUS_OK:
        return _persist(status, {
            "ok": False,
            "error": status,
            "horizon": HORIZON_ONE_PLAYER_TURN,
            "opponent_policy": OPPONENT_POLICY_NONE,
            "information_mode": INFORMATION_PUBLIC,
        })

    analysis_state = _json_load(snap.get("analysis_state_json"))
    if not isinstance(analysis_state, dict):
        return _persist(STATUS_NO_SNAPSHOT, {"ok": False, "error": STATUS_NO_SNAPSHOT})

    seat = int((bundle.get("search_decision") or {}).get("my_player_index") or 0)
    brief = _json_load(snap.get("brief_state_json")) or {}
    victory = int(brief.get("victory_score") or 8)
    dec = bundle.get("search_decision") or {}
    played = next((c for c in bundle["candidates"] if c.get("chosen")), None)
    if played is None and dec.get("chosen_line_id"):
        played = next(
            (c for c in bundle["candidates"] if c.get("line_id") == dec.get("chosen_line_id")),
            None,
        )
    played_score = None
    if played and played.get("search_state"):
        played_score = packs._my_score(played["search_state"])
    elif snap.get("my_score") is not None:
        played_score = float(snap["my_score"])

    root_state = packs.build_root_search_state(brief_state=brief, snapshot_scalars={
        "my_score": snap.get("my_score"),
        "opp_score": snap.get("opp_score"),
        "my_ready_rune_count": None,
    })
    goal_set = _json_load(dec.get("goal_set_json"))

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
        tmp_profile = _write_temp_json(parsed_profile, suffix="-profile.json")
        profile_path = str(tmp_profile)

    factory = host_factory or open_counterfactual_host
    try:
        with factory(
            analysis_state=analysis_state,
            seat=seat,
            expected_hash=expected_hash,
            profile_path=profile_path,
        ) as host:
            restored_hash = str((host.payload or {}).get("root_state_hash") or "")
            if expected_hash and restored_hash and restored_hash != expected_hash:
                return _persist(STATUS_HASH_MISMATCH, {
                    "ok": False,
                    "error": STATUS_HASH_MISMATCH,
                    "root_state_hash": restored_hash,
                    "expected_hash": expected_hash,
                })
            overlay_search = run_offline_search(
                budget=budget_used, overlay=overlay, profile_path=profile_path, seat=seat
            )
            offline_lines = _normalize_engine_lines(overlay_search)
            base_lines = None
            if overlay:
                base_search = run_offline_search(
                    budget=budget_used, overlay=None, profile_path=profile_path, seat=seat
                )
                base_lines = _normalize_engine_lines(base_search)
            comparison = compare_lines(
                played=played,
                original=bundle["candidates"],
                offline=offline_lines,
                offline_base=base_lines,
                root_state=root_state,
                victory_score=victory,
                goal_set=goal_set if isinstance(goal_set, dict) else None,
                played_score=played_score,
            )
            result = RolloutResult(
                ok=True,
                horizon=HORIZON_ONE_PLAYER_TURN,
                opponent_policy=OPPONENT_POLICY_NONE,
                information_mode=INFORMATION_PUBLIC,
                root_state_hash=restored_hash or expected_hash,
                candidate_lines=offline_lines,
                search_stats=overlay_search.get("search_stats") or {},
                assumptions=assumptions,
            ).to_dict()
            result["comparison"] = comparison
            result["base_profile_line_count"] = len(base_lines or [])
            result["goals_source"] = dec.get("goals_source")
            return _persist(STATUS_OK, result)
    except Exception as exc:
        return _persist(STATUS_ENGINE_ERROR, {
            "ok": False,
            "error": STATUS_ENGINE_ERROR,
            "detail": str(exc),
            "horizon": HORIZON_ONE_PLAYER_TURN,
            "opponent_policy": OPPONENT_POLICY_NONE,
            "information_mode": INFORMATION_PUBLIC,
        })
    finally:
        if tmp_profile is not None:
            try:
                tmp_profile.unlink()
            except OSError:
                pass


def analyze_decision(
    memory: Memory,
    *,
    game_id: str,
    turn: int,
    decision_index: int,
    budget: Optional[dict] = None,
    persist: bool = True,
    host_factory=None,
    mode: str = "outcome_rollout",
    preset: str = "deep",
    future_player_turns: int = 4,
    target: Optional[dict] = None,
    force_same_turn: bool = False,
) -> dict[str, Any]:
    """Unified entry: default multi-turn outcome rollout; same-turn on request/fallback."""
    if force_same_turn or mode in ("same_turn", "1_player_turn"):
        return analyze_same_turn_decision(
            memory,
            game_id=game_id,
            turn=turn,
            decision_index=decision_index,
            budget=budget,
            persist=persist,
            host_factory=host_factory,
        )
    from . import outcome_rollout as ocr

    return ocr.analyze_outcome_rollout(
        memory,
        game_id=game_id,
        turn=turn,
        decision_index=decision_index,
        future_player_turns=future_player_turns,
        preset=preset,
        budget_overrides=budget,
        target=target,
        persist=persist,
        host_factory=host_factory,
        include_same_turn=True,
    )


def render_markdown(result: dict) -> str:
    if str(result.get("run_kind") or "") == "outcome_rollout" or str(result.get("horizon") or "") == "multi_turn":
        from . import outcome_rollout as ocr
        return ocr.render_markdown(result)
    lines = [
        f"# Counterfactual {result.get('game_id')} t{result.get('turn')} d{result.get('decision_index')}",
        "",
        f"- status: `{result.get('status')}`",
        f"- horizon: `{result.get('horizon', HORIZON_ONE_PLAYER_TURN)}`",
        f"- opponent_policy: `{result.get('opponent_policy', OPPONENT_POLICY_NONE)}`",
        f"- information_mode: `{result.get('information_mode', INFORMATION_PUBLIC)}`",
        f"- root_hash: `{result.get('root_state_hash', '')}`",
    ]
    if result.get("error"):
        lines.append(f"- error: {result.get('error')}")
        if result.get("detail"):
            lines.append(f"- detail: {result.get('detail')}")
        return "\n".join(lines) + "\n"
    cmp_ = result.get("comparison") or {}
    played = cmp_.get("played") or {}
    lines.append(f"- played: `{played.get('moves')}` score={played.get('score')}")
    lines.append(f"- original beam: {cmp_.get('original_line_count')} lines")
    lines.append(f"- offline beam: {cmp_.get('offline_line_count')} lines")
    lines.append("")
    lines.append("## Predicate packs")
    for pack in cmp_.get("packs") or []:
        off_n = len(pack.get("offline_hard_matches") or [])
        orig_n = len(pack.get("original_hard_matches") or [])
        flag = ""
        if pack.get("offline_found_hard_match") and not pack.get("best_offline_in_original_beam"):
            flag = " **search coverage gap**"
        elif pack.get("offline_found_hard_match") and pack.get("original_beam_had_hard_match"):
            flag = " (also in original beam)"
        lines.append(
            f"- `{pack.get('pack_id')}`: offline_hard={off_n} original_hard={orig_n}{flag}"
        )
        best = (pack.get("offline_hard_matches") or [None])[0]
        if best:
            lines.append(f"  - best: `{best.get('canonical_moves')}`")
    lines.append("")
    note = (result.get("assumptions") or {}).get("note", "")
    if note:
        lines.append(f"> {note}")
        lines.append("")
    return "\n".join(lines)
