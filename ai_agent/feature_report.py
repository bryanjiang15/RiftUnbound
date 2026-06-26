#!/usr/bin/env python3
"""Feature impact & frequency report for the search tuning dataset.

Reads ``search_decisions`` (see ``memory.py`` / docs/Statistical_Analysis_Storage.md)
and summarises, per scoring feature:

  * In-play %      — how often the feature was non-zero in the chosen line
                     (i.e. actually contributed to the decision).
  * Avg |impact|   — mean absolute weighted contribution to the score across ALL
                     decisions (the per-term ``score_breakdown`` value). This is
                     the honest "how much did this feature move the score" metric.
  * Active impact  — mean absolute contribution counting only decisions where the
                     feature was in play.
  * Net dir        — mean signed contribution (＋ helped the AI, − hurt it).

Because the eval is linear, ``score_breakdown[term] = weight * feature`` is an
exact per-feature attribution, so these numbers are directly comparable.

Usage:
    python ai_agent/feature_report.py                  # default DB
    python ai_agent/feature_report.py --db ai_agent/selfplay.db
    python ai_agent/feature_report.py --sort frequency # sort by in-play %
    python ai_agent/feature_report.py --origin self_play --selector argmax

Filtering (all combine with AND):
    --turn 3              only decisions on turn 3
    --min-turn 2 --max-turn 5   turns 2-5 inclusive
    --outcome win         only decisions from games the seat won
    --seat 0              only seat-0 (player index) decisions
    --went-first 1        only decisions where the seat went first
    --mode main|reactive  --game-id <id>  --weight-version <n>
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).parent / "agent_memory.db"

# Force UTF-8 so the bar glyphs / symbols survive a non-UTF-8 console (e.g. the
# Windows cp1252 default) when output is redirected or piped.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except (AttributeError, ValueError):
    pass

# Breakdown keys that are metadata / aggregates, not per-feature contributions.
_NON_FEATURE_KEYS = {"total", "points_to_win", "shaping_clamped"}

_USE_COLOR = sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def _bold(t: str) -> str:
    return _c(t, "1")


def _dim(t: str) -> str:
    return _c(t, "2")


def _green(t: str) -> str:
    return _c(t, "32")


def _red(t: str) -> str:
    return _c(t, "31")


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        sys.exit(f"Database not found: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def gather(conn: sqlite3.Connection, *, filters: dict) -> dict:
    where = ["chosen_breakdown_json IS NOT NULL"]
    params: list = []
    # Simple equality filters.
    for col, key in (("origin", "origin"), ("selector_source", "selector"),
                     ("mode", "mode"), ("game_outcome", "outcome"),
                     ("my_player_index", "seat"), ("went_first", "went_first"),
                     ("game_id", "game_id"), ("weight_version_id", "weight_version")):
        val = filters.get(key)
        if val is not None:
            where.append(f"{col} = ?")
            params.append(val)
    # Turn range.
    if filters.get("min_turn") is not None:
        where.append("turn >= ?")
        params.append(filters["min_turn"])
    if filters.get("max_turn") is not None:
        where.append("turn <= ?")
        params.append(filters["max_turn"])
    sql = "SELECT chosen_breakdown_json FROM search_decisions WHERE " + " AND ".join(where)
    rows = conn.execute(sql, params).fetchall()

    total = 0
    # feature -> running stats
    stats: dict[str, dict] = {}
    for r in rows:
        try:
            bd = json.loads(r["chosen_breakdown_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        total += 1
        for key, val in bd.items():
            if key in _NON_FEATURE_KEYS:
                continue
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                continue
            s = stats.setdefault(key, {"sum_abs": 0.0, "sum_signed": 0.0,
                                       "active": 0, "active_abs": 0.0})
            s["sum_abs"] += abs(val)
            s["sum_signed"] += val
            if val != 0.0:
                s["active"] += 1
                s["active_abs"] += abs(val)
    return {"total": total, "stats": stats, "filters": filters}


def _filter_summary(filters: dict) -> str:
    parts = []
    simple = {
        "origin": "origin", "selector": "selector", "mode": "mode",
        "outcome": "outcome", "seat": "seat", "went_first": "went_first",
        "game_id": "game", "weight_version": "weight_v",
    }
    for key, label in simple.items():
        v = filters.get(key)
        if v is not None:
            parts.append(f"{label}={v}")
    mn, mx = filters.get("min_turn"), filters.get("max_turn")
    if mn is not None and mx is not None:
        parts.append(f"turn {mn}" if mn == mx else f"turn {mn}-{mx}")
    elif mn is not None:
        parts.append(f"turn>={mn}")
    elif mx is not None:
        parts.append(f"turn<={mx}")
    return ", ".join(parts) if parts else "no filters"


def render(data: dict, sort_key: str) -> str:
    total = data["total"]
    stats = data["stats"]
    filt = _filter_summary(data.get("filters", {}))
    if total == 0:
        return (f"No searched decisions match [{filt}] "
                "(is the DB populated / filters too strict?).")

    rows = []
    for feat, s in stats.items():
        in_play_pct = 100.0 * s["active"] / total
        avg_abs = s["sum_abs"] / total
        active_abs = (s["active_abs"] / s["active"]) if s["active"] else 0.0
        net_dir = s["sum_signed"] / total
        rows.append({
            "feature": feat,
            "in_play": in_play_pct,
            "avg_abs": avg_abs,
            "active_abs": active_abs,
            "net_dir": net_dir,
        })

    if sort_key == "frequency":
        rows.sort(key=lambda r: r["in_play"], reverse=True)
    else:  # impact
        rows.sort(key=lambda r: r["avg_abs"], reverse=True)

    name_w = max(len("Feature"), max(len(r["feature"]) for r in rows))
    max_avg = max((r["avg_abs"] for r in rows), default=0.0) or 1.0

    out: list[str] = []
    out.append("")
    out.append(_bold(f"  Feature impact & frequency — {total} searched decisions"))
    out.append(_dim(f"  filters: {filt}"))
    out.append(_dim(f"  sorted by {'in-play %' if sort_key == 'frequency' else 'average |impact|'}"))
    out.append("")
    header = (f"  {'Feature':<{name_w}}  {'In-play':>8}  {'Avg|impact|':>12}  "
              f"{'Active':>9}  {'Net dir':>9}  ")
    out.append(_bold(header))
    out.append(_dim("  " + "─" * (len(header) - 2)))

    for r in rows:
        bar_len = int(round(18 * r["avg_abs"] / max_avg))
        bar = "█" * bar_len
        dir_plain = f"{r['net_dir']:>+9.3f}"
        if r["net_dir"] > 0:
            dir_txt = _green(dir_plain)
        elif r["net_dir"] < 0:
            dir_txt = _red(dir_plain)
        else:
            dir_txt = dir_plain
        line = (f"  {r['feature']:<{name_w}}  {r['in_play']:>7.1f}%  "
                f"{r['avg_abs']:>12.3f}  {r['active_abs']:>9.3f}  {dir_txt}  "
                f"{_dim(bar)}")
        out.append(line)

    out.append("")
    # Quick callouts.
    by_impact = max(rows, key=lambda r: r["avg_abs"])
    by_freq = max(rows, key=lambda r: r["in_play"])
    out.append(_bold("  Highlights"))
    out.append(f"    Most impactful : {_green(by_impact['feature'])} "
               f"(avg |impact| {by_impact['avg_abs']:.3f})")
    out.append(f"    Most frequent  : {_green(by_freq['feature'])} "
               f"(in play {by_freq['in_play']:.1f}% of decisions)")
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Feature impact & frequency report.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH,
                        help=f"SQLite DB path (default: {DEFAULT_DB_PATH})")
    parser.add_argument("--sort", choices=["impact", "frequency"], default="impact",
                        help="Sort order (default: impact)")
    parser.add_argument("--origin", help="Filter by origin (self_play|vs_human|vs_heuristic)")
    parser.add_argument("--selector", help="Filter by selector_source (argmax|llm|fallback)")
    parser.add_argument("--mode", help="Filter by search mode (main|reactive)")
    parser.add_argument("--outcome", help="Filter by game_outcome (win|loss|draw)")
    parser.add_argument("--seat", type=int, help="Filter by deciding seat (my_player_index, 0 or 1)")
    parser.add_argument("--went-first", type=int, choices=[0, 1], dest="went_first",
                        help="Filter by whether the seat went first (1) or not (0)")
    parser.add_argument("--game-id", dest="game_id", help="Filter to a single game_id")
    parser.add_argument("--weight-version", type=int, dest="weight_version",
                        help="Filter by weight_version_id")
    parser.add_argument("--min-turn", type=int, dest="min_turn", help="Only decisions on turn >= N")
    parser.add_argument("--max-turn", type=int, dest="max_turn", help="Only decisions on turn <= N")
    parser.add_argument("--turn", type=int, help="Only decisions on exactly turn N (shortcut)")
    args = parser.parse_args(argv)

    min_turn = args.min_turn
    max_turn = args.max_turn
    if args.turn is not None:
        min_turn = max_turn = args.turn

    filters = {
        "origin": args.origin,
        "selector": args.selector,
        "mode": args.mode,
        "outcome": args.outcome,
        "seat": args.seat,
        "went_first": args.went_first,
        "game_id": args.game_id,
        "weight_version": args.weight_version,
        "min_turn": min_turn,
        "max_turn": max_turn,
    }

    conn = _connect(args.db)
    try:
        data = gather(conn, filters=filters)
    finally:
        conn.close()
    print(render(data, args.sort))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
