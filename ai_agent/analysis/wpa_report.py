"""Turn / exchange WPA reports and associative card-associated WPA."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any, Optional

from . import wpa_model as wm

SWING_ABS_MIN = 0.10


def load_turn_rows(
    conn: sqlite3.Connection,
    *,
    origin: Optional[str] = None,
    weight_version_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Load turn_snapshots joined to canonical game outcomes.

    Filters by origin / weight_version via search_decisions so policy changes
    are not silently mixed. Both seats of a game stay together via game_id.
    """
    where = ["g.winner_index IS NOT NULL"]
    params: list[Any] = []
    origin_join = ""
    if origin is not None or weight_version_id is not None:
        origin_join = """
            AND EXISTS (
                SELECT 1 FROM search_decisions sd
                WHERE sd.game_id = ts.game_id
        """
        if origin is not None:
            origin_join += " AND sd.origin = ?"
            params.append(origin)
        if weight_version_id is not None:
            origin_join += " AND sd.weight_version_id = ?"
            params.append(weight_version_id)
        origin_join += ")"
    sql = f"""
        SELECT
            ts.game_id, ts.turn, ts.my_player_index, ts.turn_player_index,
            ts.my_score, ts.opp_score, ts.my_energy, ts.board_might_diff,
            ts.cards_in_hand, ts.cards_in_hand_opp, ts.bf_control_net,
            ts.my_rune_count, ts.my_ready_rune_count,
            g.winner_index, g.first_player_index, g.timestamp AS game_timestamp,
            g.p0_score, g.p1_score
        FROM turn_snapshots ts
        JOIN games g ON g.game_id = ts.game_id
        WHERE {' AND '.join(where)} {origin_join}
        ORDER BY g.timestamp ASC, ts.game_id, ts.turn, ts.my_player_index
    """
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    return rows


def assign_splits(rows: list[dict], *, seed: int = 0) -> list[dict]:
    game_ids: list[str] = []
    seen: set[str] = set()
    for r in rows:
        gid = str(r["game_id"])
        if gid not in seen:
            seen.add(gid)
            game_ids.append(gid)
    splits = wm.chronological_game_splits(game_ids, seed=seed)
    out = []
    for r in rows:
        rec = dict(r)
        gid = str(r["game_id"])
        if gid in splits["train"]:
            rec["split"] = "train"
        elif gid in splits["calibration"]:
            rec["split"] = "calibration"
        else:
            rec["split"] = "test"
        out.append(rec)
    return out


def compute_turn_wpa(predicted: list[dict]) -> list[dict]:
    """turn_wpa = P(win after completed turn) - P(win at prior snapshot, same seat)."""
    by_seat: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in predicted:
        my_pi = row.get("my_player_index")
        if my_pi is None:
            continue
        by_seat[(str(row["game_id"]), int(my_pi))].append(row)
    out: list[dict] = []
    for (_gid, _pi), seq in by_seat.items():
        seq = sorted(seq, key=lambda r: int(r.get("turn") or 0))
        prev_p = None
        for row in seq:
            rec = dict(row)
            p = float(row.get("p_win") or 0.0)
            rec["turn_wpa"] = None if prev_p is None else p - prev_p
            rec["prior_p_win"] = prev_p
            out.append(rec)
            prev_p = p
    return out


def compute_exchange_wpa(turn_rows: list[dict]) -> list[dict]:
    """exchange_wpa spans the player's turn plus the opponent's observed reply."""
    by_game_seat: dict[tuple[str, int], dict[int, dict]] = defaultdict(dict)
    for row in turn_rows:
        my_pi = row.get("my_player_index")
        if my_pi is None or row.get("turn_wpa") is None:
            continue
        by_game_seat[(str(row["game_id"]), int(my_pi))][int(row["turn"])] = row
    out = []
    for (gid, pi), by_turn in by_game_seat.items():
        for turn, row in by_turn.items():
            # Own completed turn T plus opponent reply which is recorded as
            # turn_player_index != me on the next snapshot for this seat (turn T+1).
            nxt = by_turn.get(turn + 1)
            rec = dict(row)
            if nxt is None or nxt.get("turn_wpa") is None:
                rec["exchange_wpa"] = None
            else:
                rec["exchange_wpa"] = float(row["turn_wpa"]) + float(nxt["turn_wpa"])
            out.append(rec)
    return out


def swing_turns(rows: list[dict], *, split: str = "test") -> list[dict]:
    """Top decile of |turn_wpa| on the held-out split, requiring abs >= 0.10."""
    held = [
        r for r in rows
        if r.get("split") == split and r.get("turn_wpa") is not None
    ]
    if not held:
        return []
    abs_vals = sorted((abs(float(r["turn_wpa"])) for r in held), reverse=True)
    cutoff_index = max(0, (len(abs_vals) + 9) // 10 - 1)
    cutoff = abs_vals[cutoff_index]
    swings = [
        r for r in held
        if abs(float(r["turn_wpa"])) >= SWING_ABS_MIN and abs(float(r["turn_wpa"])) >= cutoff
    ]
    swings.sort(key=lambda r: abs(float(r["turn_wpa"])), reverse=True)
    return swings


def load_played_cards(conn: sqlite3.Connection) -> dict[tuple[str, int, int], list[str]]:
    """(game_id, turn, my_player_index) -> card_def_ids played that turn."""
    conn.row_factory = sqlite3.Row
    out: dict[tuple[str, int, int], list[str]] = defaultdict(list)
    for r in conn.execute(
        """
        SELECT game_id, turn, my_player_index, card_def_id
        FROM card_events
        WHERE event='played' AND my_player_index IS NOT NULL
        """
    ):
        key = (str(r["game_id"]), int(r["turn"]), int(r["my_player_index"]))
        out[key].append(str(r["card_def_id"]))
    return out


def card_associated_wpa(
    turn_rows: list[dict],
    played_cards: dict[tuple[str, int, int], list[str]],
    *,
    min_plays: int = 20,
    seed: int = 0,
) -> list[dict[str, Any]]:
    """Associative card WPA: mean own-turn WPA when the card was played minus baseline.

    Multi-card turns list all contributing cards and report multi_card_turn_share.
    Does not split the delta or claim an individual card caused it.
    """
    own_turns = [
        r for r in turn_rows
        if r.get("turn_wpa") is not None
        and r.get("my_player_index") is not None
        and r.get("turn_player_index") is not None
        and int(r["my_player_index"]) == int(r["turn_player_index"])
    ]
    if not own_turns:
        return []
    baseline_values = [float(r["turn_wpa"]) for r in own_turns]
    baseline = sum(baseline_values) / len(baseline_values)

    per_card_game_vals: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    multi_card_turns = 0
    card_turn_count: dict[str, int] = defaultdict(int)
    card_multi_count: dict[str, int] = defaultdict(int)

    for row in own_turns:
        key = (str(row["game_id"]), int(row["turn"]), int(row["my_player_index"]))
        cards = list(dict.fromkeys(played_cards.get(key, [])))
        if not cards:
            continue
        if len(cards) > 1:
            multi_card_turns += 1
        wpa = float(row["turn_wpa"])
        gid = str(row["game_id"])
        for cid in cards:
            per_card_game_vals[cid][gid].append(wpa)
            card_turn_count[cid] += 1
            if len(cards) > 1:
                card_multi_count[cid] += 1

    out = []
    for cid, by_game in per_card_game_vals.items():
        plays = card_turn_count[cid]
        # Game-level means for bootstrap (one value per game).
        game_means = [sum(vs) / len(vs) for vs in by_game.values() if vs]
        if plays < min_plays:
            ci = {"mean": sum(game_means) / len(game_means) if game_means else float("nan"),
                  "lo": float("nan"), "hi": float("nan")}
        else:
            ci = wm.bootstrap_mean_ci(game_means, seed=seed)
        assoc = (ci["mean"] - baseline) if game_means else float("nan")
        out.append({
            "card_def_id": cid,
            "plays": plays,
            "games": len(by_game),
            "mean_own_turn_wpa": ci["mean"],
            "baseline_own_turn_wpa": baseline,
            "card_associated_wpa": assoc,
            "ci95_lo": None if plays < min_plays else (ci["lo"] - baseline),
            "ci95_hi": None if plays < min_plays else (ci["hi"] - baseline),
            "multi_card_turn_share": (card_multi_count[cid] / plays) if plays else 0.0,
            "low_sample": plays < min_plays,
        })
    out.sort(key=lambda r: (r["low_sample"], -(abs(r["card_associated_wpa"]) if r["card_associated_wpa"] == r["card_associated_wpa"] else 0)))
    return out


def validate_db_readiness(conn: sqlite3.Connection) -> dict[str, Any]:
    """Confirm a self-play DB actually contains turn_snapshots, card_events, canonical outcomes."""
    tables = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    checks = {
        "has_turn_snapshots": "turn_snapshots" in tables,
        "has_card_events": "card_events" in tables,
        "has_games": "games" in tables,
        "has_winner_index_column": False,
        "finished_games": 0,
        "games_with_winner_index": 0,
        "turn_snapshot_rows": 0,
        "card_event_rows": 0,
        "decision_snapshots_with_analysis": 0,
    }
    if "games" in tables:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(games)").fetchall()}
        checks["has_winner_index_column"] = "winner_index" in cols
        checks["finished_games"] = int(conn.execute(
            "SELECT COUNT(*) FROM games WHERE outcome IS NOT NULL"
        ).fetchone()[0])
        if "winner_index" in cols:
            checks["games_with_winner_index"] = int(conn.execute(
                "SELECT COUNT(*) FROM games WHERE winner_index IS NOT NULL"
            ).fetchone()[0])
    if "turn_snapshots" in tables:
        checks["turn_snapshot_rows"] = int(conn.execute("SELECT COUNT(*) FROM turn_snapshots").fetchone()[0])
    if "card_events" in tables:
        checks["card_event_rows"] = int(conn.execute("SELECT COUNT(*) FROM card_events").fetchone()[0])
    if "decision_snapshots" in tables:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(decision_snapshots)").fetchall()}
        if "analysis_state_json" in cols:
            checks["decision_snapshots_with_analysis"] = int(conn.execute(
                "SELECT COUNT(*) FROM decision_snapshots WHERE analysis_state_json IS NOT NULL"
            ).fetchone()[0])
    checks["ready_for_wpa"] = (
        checks["has_turn_snapshots"]
        and checks["turn_snapshot_rows"] > 0
        and checks["has_winner_index_column"]
        and checks["games_with_winner_index"] > 0
    )
    checks["ready_for_counterfactual"] = checks["decision_snapshots_with_analysis"] > 0
    return checks


def build_report(
    conn: sqlite3.Connection,
    *,
    origin: Optional[str] = None,
    weight_version_id: Optional[int] = None,
    min_plays: int = 20,
    seed: int = 0,
) -> dict[str, Any]:
    readiness = validate_db_readiness(conn)
    rows = assign_splits(load_turn_rows(conn, origin=origin, weight_version_id=weight_version_id), seed=seed)
    n_games = len({r["game_id"] for r in rows})
    model = wm.fit_wpa_model(rows, seed=seed) if rows else {"ok": False, "error": "no_rows"}
    predicted = wm.predict_rows(rows, model) if model.get("ok") else []
    with_turn = compute_turn_wpa(predicted)
    with_ex = compute_exchange_wpa(with_turn)
    swings = swing_turns(with_ex) if model.get("ok") else []
    played = load_played_cards(conn)
    cards = card_associated_wpa(with_ex, played, min_plays=min_plays, seed=seed) if model.get("ok") else []
    return {
        "readiness": readiness,
        "filters": {"origin": origin, "weight_version_id": weight_version_id},
        "n_rows": len(rows),
        "n_games": n_games,
        "model": {k: v for k, v in model.items() if k != "fit"} | (
            {"feature_names": (model.get("fit") or {}).get("feature_names")} if model.get("ok") else {}
        ),
        "fit": model.get("fit"),
        "platt": model.get("platt"),
        "swing_turns": [
            {
                "game_id": s["game_id"],
                "turn": s["turn"],
                "my_player_index": s["my_player_index"],
                "turn_wpa": s["turn_wpa"],
                "exchange_wpa": s.get("exchange_wpa"),
                "p_win": s.get("p_win"),
                "split": s.get("split"),
            }
            for s in swings[:50]
        ],
        "card_associated_wpa": cards,
        "notes": [
            "card_associated_wpa is associative, not causal.",
            "Multi-card turns are not split across cards.",
            "Event-level card WPA requires future pre/post-action snapshots.",
            "V1 WPA does not use opponent hidden information.",
        ],
    }


def render_markdown(report: dict) -> str:
    lines = ["# WPA / swing-turn report", ""]
    ready = report.get("readiness") or {}
    lines.append(f"- finished games with winner_index: {ready.get('games_with_winner_index')}")
    lines.append(f"- turn_snapshots: {ready.get('turn_snapshot_rows')}")
    lines.append(f"- analysis snapshots: {ready.get('decision_snapshots_with_analysis')}")
    model = report.get("model") or {}
    if not model.get("ok"):
        lines.append(f"- model: failed ({model.get('error')})")
        return "\n".join(lines) + "\n"
    test = model.get("test") or {}
    lines.append(f"- n_games: {model.get('n_games')} publishable={model.get('publishable')} provisional={model.get('provisional')}")
    lines.append(
        f"- held-out Brier: {test.get('brier')} (baseline {test.get('baseline_brier')}) "
        f"log_loss={test.get('log_loss')} AUC={test.get('roc_auc')} ECE={test.get('ece')}"
    )
    if model.get("refuse_rankings"):
        lines.append("- rankings refused (<150 finished games)")
    lines.append("")
    lines.append("## Top swing turns (held-out)")
    swings = report.get("swing_turns") or []
    if not swings:
        lines.append("- (none)")
    for s in swings[:20]:
        lines.append(
            f"- {s.get('game_id')} t{s.get('turn')} seat{s.get('my_player_index')} "
            f"ΔWP={s.get('turn_wpa'):+.3f} exchange={s.get('exchange_wpa')}"
        )
    lines.append("")
    lines.append("## Card-associated WPA (associative)")
    cards = report.get("card_associated_wpa") or []
    shown = [c for c in cards if not c.get("low_sample")][:25]
    if not shown:
        lines.append("- (none above min-plays)")
    for c in shown:
        lines.append(
            f"- `{c['card_def_id']}` plays={c['plays']} assoc_wpa={c['card_associated_wpa']:+.3f} "
            f"CI=({c.get('ci95_lo')}, {c.get('ci95_hi')}) multi_share={c['multi_card_turn_share']:.2f}"
        )
    lines.append("")
    for note in report.get("notes") or []:
        lines.append(f"> {note}")
    lines.append("")
    return "\n".join(lines)
