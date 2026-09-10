#!/usr/bin/env python3
"""Feature impact & frequency report for the search tuning dataset.

Reads ``search_decisions.chosen_breakdown_json`` and joins term ids to
``Data/AI/feature_registry.json`` so state vs action vs terminal stay separate.

  * In-play %       — how often the term was non-zero on the chosen line
  * Avg |impact|    — mean |score_breakdown[term]| across all matching decisions
  * Active          — mean |impact| on decisions where the term was in play
  * Mean contrib    — mean *signed* contribution of the chosen line
                      (not a quality signal by itself)
  * Δ(W−L)          — mean contrib in seat-wins minus seat-losses
                      (``search_decisions.game_outcome``; unlabeled rows skipped)

Because the eval is linear, ``score_breakdown[term] = weight * feature`` is an
exact per-term attribution.

Usage:
    python ai_agent/feature_report.py
    python ai_agent/feature_report.py --db ai_agent/selfplay.db --selector argmax
    python ai_agent/feature_report.py --latest-weight-version --sort outcome

Filtering (all combine with AND):
    --turn / --min-turn / --max-turn
    --outcome win|loss|draw   (seat-relative game_outcome)
    --seat 0|1  --went-first 0|1  --mode main|reactive
    --origin --game-id --weight-version / --latest-weight-version
    --group state|action|terminal|end_of_turn|unregistered
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = Path(__file__).parent / "agent_memory.db"
DEFAULT_MANIFEST_PATH = REPO_ROOT / "Data" / "AI" / "feature_registry.json"

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except (AttributeError, ValueError):
    pass

# Metadata keys on score_breakdown, not scored terms.
_NON_FEATURE_KEYS = {"total", "points_to_win", "shaping_clamped"}
_SPECIAL_GROUPS = {
    "win_game": "terminal",
    "end_of_turn": "end_of_turn",
}
_GROUP_ORDER = ("terminal", "state", "action", "end_of_turn", "unregistered")

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


def load_registry_groups(manifest_path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, str]:
    """Map breakdown term id → registry group (state/action/situational)."""
    try:
        data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    for spec in data.get("specs") or []:
        if not isinstance(spec, dict):
            continue
        term_id = spec.get("id")
        group = spec.get("group") or "unregistered"
        if term_id:
            out[str(term_id)] = str(group)
    return out


def term_group(term_id: str, registry: dict[str, str]) -> str:
    if term_id in _SPECIAL_GROUPS:
        return _SPECIAL_GROUPS[term_id]
    return registry.get(term_id, "unregistered")


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        sys.exit(f"Database not found: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _where_clause(filters: dict) -> tuple[str, list]:
    where = ["chosen_breakdown_json IS NOT NULL"]
    params: list = []
    for col, key in (
        ("origin", "origin"),
        ("selector_source", "selector"),
        ("mode", "mode"),
        ("game_outcome", "outcome"),
        ("my_player_index", "seat"),
        ("went_first", "went_first"),
        ("game_id", "game_id"),
        ("weight_version_id", "weight_version"),
    ):
        val = filters.get(key)
        if val is not None:
            where.append(f"{col} = ?")
            params.append(val)
    if filters.get("min_turn") is not None:
        where.append("turn >= ?")
        params.append(filters["min_turn"])
    if filters.get("max_turn") is not None:
        where.append("turn <= ?")
        params.append(filters["max_turn"])
    return " AND ".join(where), params


def resolve_latest_weight_version(conn: sqlite3.Connection, filters: dict) -> Optional[int]:
    """Latest weight_version_id among rows that match the other filters."""
    probe = dict(filters)
    probe.pop("weight_version", None)
    where_sql, params = _where_clause(probe)
    row = conn.execute(
        "SELECT MAX(weight_version_id) AS v FROM search_decisions WHERE " + where_sql,
        params,
    ).fetchone()
    if row is None or row["v"] is None:
        return None
    return int(row["v"])


def gather(
    conn: sqlite3.Connection,
    *,
    filters: dict,
    registry: Optional[dict[str, str]] = None,
) -> dict:
    registry = load_registry_groups() if registry is None else registry
    where_sql, params = _where_clause(filters)
    sql = (
        "SELECT chosen_breakdown_json, game_outcome, weight_version_id "
        "FROM search_decisions WHERE " + where_sql
    )
    rows = conn.execute(sql, params).fetchall()

    total = 0
    n_win = 0
    n_loss = 0
    n_unlabeled = 0
    weight_versions: set[int] = set()
    stats: dict[str, dict] = {}

    for r in rows:
        try:
            bd = json.loads(r["chosen_breakdown_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(bd, dict):
            continue
        total += 1
        outcome = str(r["game_outcome"] or "").lower()
        if outcome == "win":
            n_win += 1
        elif outcome == "loss":
            n_loss += 1
        else:
            n_unlabeled += 1
        if r["weight_version_id"] is not None:
            try:
                weight_versions.add(int(r["weight_version_id"]))
            except (TypeError, ValueError):
                pass
        for key, val in bd.items():
            if key in _NON_FEATURE_KEYS:
                continue
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                continue
            s = stats.setdefault(
                key,
                {
                    "group": term_group(key, registry),
                    "sum_abs": 0.0,
                    "sum_signed": 0.0,
                    "active": 0,
                    "active_abs": 0.0,
                    "sum_win": 0.0,
                    "sum_loss": 0.0,
                },
            )
            s["sum_abs"] += abs(val)
            s["sum_signed"] += val
            if val != 0.0:
                s["active"] += 1
                s["active_abs"] += abs(val)
            if outcome == "win":
                s["sum_win"] += val
            elif outcome == "loss":
                s["sum_loss"] += val

    return {
        "total": total,
        "n_win": n_win,
        "n_loss": n_loss,
        "n_unlabeled": n_unlabeled,
        "weight_versions": sorted(weight_versions),
        "mixed_weight_versions": len(weight_versions) > 1,
        "registry_loaded": bool(registry),
        "stats": stats,
        "filters": filters,
    }


def _filter_summary(filters: dict) -> str:
    parts = []
    simple = {
        "origin": "origin",
        "selector": "selector",
        "mode": "mode",
        "outcome": "outcome",
        "seat": "seat",
        "went_first": "went_first",
        "game_id": "game",
        "weight_version": "weight_v",
        "group": "group",
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


def _rows_from_stats(data: dict, group_filter: Optional[str] = None) -> list[dict]:
    total = data["total"] or 1
    n_win = data["n_win"]
    n_loss = data["n_loss"]
    rows = []
    for feat, s in data["stats"].items():
        group = s["group"]
        if group_filter and group != group_filter:
            continue
        mean_win = (s["sum_win"] / n_win) if n_win else None
        mean_loss = (s["sum_loss"] / n_loss) if n_loss else None
        delta = None
        if mean_win is not None and mean_loss is not None:
            delta = mean_win - mean_loss
        rows.append(
            {
                "feature": feat,
                "group": group,
                "in_play": 100.0 * s["active"] / total,
                "avg_abs": s["sum_abs"] / total,
                "active_abs": (s["active_abs"] / s["active"]) if s["active"] else 0.0,
                "net_dir": s["sum_signed"] / total,
                "mean_win": mean_win,
                "mean_loss": mean_loss,
                "delta": delta,
            }
        )
    return rows


def render(data: dict, sort_key: str, group_filter: Optional[str] = None) -> str:
    total = data["total"]
    filt = _filter_summary({**data.get("filters", {}), "group": group_filter})
    if total == 0:
        return (
            f"No searched decisions match [{filt}] "
            "(is the DB populated / filters too strict?)."
        )

    rows = _rows_from_stats(data, group_filter)
    if not rows:
        return f"No scoring terms match [{filt}]."

    if sort_key == "frequency":
        rows.sort(key=lambda r: r["in_play"], reverse=True)
    elif sort_key == "outcome":
        rows.sort(
            key=lambda r: abs(r["delta"]) if r["delta"] is not None else -1.0,
            reverse=True,
        )
    else:
        rows.sort(key=lambda r: r["avg_abs"], reverse=True)

    name_w = max(len("Feature"), max(len(r["feature"]) for r in rows))
    group_w = max(len("Group"), max(len(r["group"]) for r in rows))
    max_avg = max((r["avg_abs"] for r in rows), default=0.0) or 1.0

    out: list[str] = []
    out.append("")
    out.append(
        _bold(
            f"  Feature impact — {total} searched decisions "
            f"(win {data['n_win']} / loss {data['n_loss']} / unlabeled {data['n_unlabeled']})"
        )
    )
    out.append(_dim(f"  filters: {filt}"))
    sort_label = {
        "frequency": "in-play %",
        "outcome": "|Δ(W−L)|",
        "impact": "average |impact|",
    }.get(sort_key, sort_key)
    out.append(_dim(f"  sorted by {sort_label}"))
    if not data.get("registry_loaded"):
        out.append(_dim("  registry: missing — terms are unregistered; regenerate feature_registry.json"))
    else:
        out.append(_dim("  registry: Data/AI/feature_registry.json (state vs action vs terminal)"))
    versions = data.get("weight_versions") or []
    if data.get("mixed_weight_versions"):
        out.append(
            _dim(
                f"  weight_versions mixed: {versions} — pass --weight-version or "
                "--latest-weight-version before comparing terms"
            )
        )
    elif versions:
        out.append(_dim(f"  weight_version_id: {versions[0]}"))
    out.append(
        _dim(
            "  Mean contrib = signed chosen-line term (not quality). "
            "Δ(W−L) = mean contrib in seat-wins minus seat-losses."
        )
    )
    out.append("")

    header = (
        f"  {'Feature':<{name_w}}  {'Group':<{group_w}}  {'In-play':>8}  "
        f"{'Avg|impact|':>12}  {'Active':>9}  {'Mean contrib':>12}  {'Δ(W−L)':>9}  "
    )
    out.append(_bold(header))
    out.append(_dim("  " + "─" * (len(header) - 2)))

    def _fmt_signed(v: Optional[float], width: int = 9) -> str:
        if v is None:
            return f"{'—':>{width}}"
        plain = f"{v:>+{width}.3f}"
        if v > 0:
            return _green(plain)
        if v < 0:
            return _red(plain)
        return plain

    grouped = {g: [r for r in rows if r["group"] == g] for g in _GROUP_ORDER}
    extra = [r for r in rows if r["group"] not in _GROUP_ORDER]
    sections = [(g, grouped[g]) for g in _GROUP_ORDER if grouped[g]]
    if extra:
        sections.append(("other", extra))

    first = True
    for group_name, group_rows in sections:
        if not first:
            out.append("")
        first = False
        if group_filter is None and len(sections) > 1:
            out.append(_dim(f"  — {group_name} —"))
        for r in group_rows:
            bar_len = int(round(14 * r["avg_abs"] / max_avg))
            bar = "█" * bar_len
            line = (
                f"  {r['feature']:<{name_w}}  {r['group']:<{group_w}}  "
                f"{r['in_play']:>7.1f}%  {r['avg_abs']:>12.3f}  {r['active_abs']:>9.3f}  "
                f"{_fmt_signed(r['net_dir'], 12)}  {_fmt_signed(r['delta'])}  "
                f"{_dim(bar)}"
            )
            out.append(line)

    out.append("")
    by_impact = max(rows, key=lambda r: r["avg_abs"])
    by_freq = max(rows, key=lambda r: r["in_play"])
    out.append(_bold("  Highlights"))
    out.append(
        f"    Most |impact| : {_green(by_impact['feature'])} "
        f"({by_impact['group']}, avg |impact| {by_impact['avg_abs']:.3f})"
    )
    out.append(
        f"    Most frequent : {_green(by_freq['feature'])} "
        f"(in play {by_freq['in_play']:.1f}%)"
    )
    with_delta = [r for r in rows if r["delta"] is not None]
    if with_delta:
        by_delta = max(with_delta, key=lambda r: abs(r["delta"]))
        out.append(
            f"    Largest Δ(W−L): {_green(by_delta['feature'])} "
            f"({by_delta['delta']:+.3f}; win {data['n_win']} / loss {data['n_loss']})"
        )
    elif data["n_win"] == 0 or data["n_loss"] == 0:
        out.append(
            _dim("    Δ(W−L) omitted — need both seat-wins and seat-losses in this slice.")
        )
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Feature impact & frequency report.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH,
                        help=f"SQLite DB path (default: {DEFAULT_DB_PATH})")
    parser.add_argument(
        "--sort",
        choices=["impact", "frequency", "outcome"],
        default="impact",
        help="Sort order (default: impact). outcome = |Δ(W−L)|",
    )
    parser.add_argument(
        "--origin",
        help="Filter by origin (self_play|vs_human|vs_heuristic)",
    )
    parser.add_argument(
        "--selector",
        help="Filter by selector_source (argmax|llm|reasoner|single|fallback)",
    )
    parser.add_argument("--mode", help="Filter by search mode (main|reactive)")
    parser.add_argument("--outcome", help="Filter by seat-relative game_outcome (win|loss|draw)")
    parser.add_argument("--seat", type=int, help="Filter by deciding seat (my_player_index, 0 or 1)")
    parser.add_argument("--went-first", type=int, choices=[0, 1], dest="went_first",
                        help="Filter by whether the seat went first (1) or not (0)")
    parser.add_argument("--game-id", dest="game_id", help="Filter to a single game_id")
    parser.add_argument("--weight-version", type=int, dest="weight_version",
                        help="Filter by weight_version_id")
    parser.add_argument(
        "--latest-weight-version",
        action="store_true",
        dest="latest_weight_version",
        help="Restrict to MAX(weight_version_id) in the filtered slice",
    )
    parser.add_argument(
        "--group",
        choices=list(_GROUP_ORDER),
        help="Only print this registry group",
    )
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
        if args.latest_weight_version:
            latest = resolve_latest_weight_version(conn, filters)
            if latest is None:
                print("No weight_version_id in this slice; cannot apply --latest-weight-version.")
                return 1
            filters["weight_version"] = latest
        data = gather(conn, filters=filters)
    finally:
        conn.close()
    print(render(data, args.sort, args.group))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
