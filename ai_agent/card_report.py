#!/usr/bin/env python3
"""Per-card statistics report (storage doc §3).

Reads ``card_events`` (see ``memory.py`` / docs/Statistical_Analysis_Storage.md),
joins game outcomes, and summarises per BASE ``card_def_id``:

  * Seen / Played  — games the card was drawn-or-opened / actually played in.
  * Draw %         — games seen ÷ games (how often it shows up).
  * Play %         — games played ÷ games.
  * Play|Drawn %   — played ÷ drawn (flags dead / situational cards).
  * Mull %         — mulliganed ÷ drawn.
  * Stuck %        — left in hand at game end ÷ drawn (clogged the hand).
  * Avg turn       — average turn the card was played (curve position).
  * Avg ENG        — average energy spent to play it.
  * Deaths         — times it died after being played.
  * WR|Played      — win rate of games it was played in (survivorship-biased;
                     prefer this only as a coarse signal, see doc §3 caveats).

The aggregation key is always the base ``card_def_id`` stamped on each event —
never reverse-engineered from instance_id (doc §3 join-key note).

Usage:
    python ai_agent/card_report.py                       # default DB
    python ai_agent/card_report.py --db ai_agent/selfplay.db
    python ai_agent/card_report.py --sort play_rate      # sort column
    python ai_agent/card_report.py --sort win_rate --desc
    python ai_agent/card_report.py --min-plays 0         # include rare cards

Sort keys:
    played (default), seen, draw_rate, play_rate, play_when_drawn,
    mulligan_rate, stuck_rate, avg_turn, avg_energy, deaths, win_rate, card

Filtering (all combine with AND):
    --seat 0              only cards reported by seat 0 (my_player_index)
    --origin self_play    only games with this origin (joined from search_decisions)
    --min-plays N         move cards with < N plays into a separate low-sample
                          section (default 20, per the doc's sample-size caveat)
"""
from __future__ import annotations

import argparse
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

_USE_COLOR = sys.stdout.isatty()

# Sort key -> (row field, default descending?). 'card' sorts ascending by name.
_SORT_FIELDS = {
    "played": ("played", True),
    "seen": ("games_seen", True),
    "draw_rate": ("draw_rate", True),
    "play_rate": ("play_rate", True),
    "play_when_drawn": ("play_when_drawn_rate", True),
    "mulligan_rate": ("mulligan_rate", True),
    "stuck_rate": ("stuck_in_hand_rate", True),
    "avg_turn": ("avg_turn_played", True),
    "avg_energy": ("avg_energy_spent", True),
    "deaths": ("deaths", True),
    "win_rate": ("win_rate_when_played", True),
    "card": ("card_def_id", False),
}


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
    has_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='card_events'"
    ).fetchone()
    if has_table is None:
        return {"games_total": 0, "base_win_rate": None, "cards": [],
                "filters": filters, "no_table": True}

    where = ["1=1"]
    params: list = []
    if filters.get("seat") is not None:
        where.append("ce.my_player_index = ?")
        params.append(filters["seat"])

    origin = filters.get("origin")
    # Origin lives on search_decisions, not card_events; restrict to games that
    # have at least one decision with this origin when the filter is set.
    origin_games: set | None = None
    if origin is not None:
        rows = conn.execute(
            "SELECT DISTINCT game_id FROM search_decisions WHERE origin = ?",
            (origin,),
        ).fetchall()
        origin_games = {r["game_id"] for r in rows}

    games_total = conn.execute("SELECT COUNT(*) AS n FROM games").fetchone()["n"] or 0
    base_win_rate = None
    if games_total:
        wins = conn.execute(
            "SELECT COUNT(*) AS n FROM games WHERE outcome='win'"
        ).fetchone()["n"] or 0
        base_win_rate = wins / games_total

    where_sql = " AND ".join(where)
    rows = conn.execute(
        f"""
        SELECT
            card_def_id,
            COUNT(DISTINCT CASE WHEN event IN ('drawn','in_opening_hand')
                  THEN game_id END)                                  AS games_seen,
            COUNT(DISTINCT CASE WHEN event='played' THEN game_id END) AS games_played,
            SUM(CASE WHEN event='drawn' THEN 1 ELSE 0 END)           AS drawn,
            SUM(CASE WHEN event='in_opening_hand' THEN 1 ELSE 0 END) AS opening_hand,
            SUM(CASE WHEN event='played' THEN 1 ELSE 0 END)          AS played,
            SUM(CASE WHEN event='discarded' THEN 1 ELSE 0 END)       AS discarded,
            SUM(CASE WHEN event='mulliganed' THEN 1 ELSE 0 END)      AS mulliganed,
            SUM(CASE WHEN event='scored' THEN 1 ELSE 0 END)          AS scored,
            SUM(CASE WHEN event='died' THEN 1 ELSE 0 END)            AS died,
            SUM(CASE WHEN event='left_in_hand_at_end' THEN 1 ELSE 0 END) AS stuck,
            AVG(CASE WHEN event='played' THEN turn END)             AS avg_turn_played,
            AVG(CASE WHEN event='played' THEN energy_spent END)    AS avg_energy_spent
        FROM card_events ce
        WHERE {where_sql}
        GROUP BY card_def_id
        """,
        params,
    ).fetchall()

    # Win-rate-when-played: distinct (card, game) played, joined to outcome.
    wr_rows = conn.execute(
        f"""
        SELECT ce.card_def_id AS card_def_id,
               ce.game_id AS game_id,
               g.outcome AS outcome
        FROM (
            SELECT DISTINCT card_def_id, game_id, my_player_index
            FROM card_events ce WHERE {where_sql} AND event='played'
        ) ce
        JOIN games g ON g.game_id = ce.game_id
        WHERE g.outcome IS NOT NULL
        """,
        params,
    ).fetchall()
    wr_by_card: dict[str, list[int]] = {}
    for r in wr_rows:
        if origin_games is not None and r["game_id"] not in origin_games:
            continue
        played_games, played_wins = wr_by_card.setdefault(r["card_def_id"], [0, 0])
        wr_by_card[r["card_def_id"]][0] = played_games + 1
        if r["outcome"] == "win":
            wr_by_card[r["card_def_id"]][1] = played_wins + 1

    cards: list[dict] = []
    for r in rows:
        drawn = r["drawn"] or 0
        played = r["played"] or 0
        pg, pw = wr_by_card.get(r["card_def_id"], [0, 0])
        cards.append({
            "card_def_id": r["card_def_id"],
            "games_seen": r["games_seen"] or 0,
            "games_played": r["games_played"] or 0,
            "draw_rate": (r["games_seen"] or 0) / games_total if games_total else None,
            "play_rate": (r["games_played"] or 0) / games_total if games_total else None,
            "play_when_drawn_rate": played / drawn if drawn else None,
            "mulligan_rate": (r["mulliganed"] or 0) / drawn if drawn else None,
            "stuck_in_hand_rate": (r["stuck"] or 0) / drawn if drawn else None,
            "avg_turn_played": r["avg_turn_played"],
            "avg_energy_spent": r["avg_energy_spent"],
            "drawn": drawn,
            "played": played,
            "discarded": r["discarded"] or 0,
            "scored": r["scored"] or 0,
            "deaths": r["died"] or 0,
            "win_rate_when_played": (pw / pg) if pg else None,
        })

    return {
        "games_total": games_total,
        "base_win_rate": base_win_rate,
        "cards": cards,
        "filters": filters,
    }


def _filter_summary(filters: dict) -> str:
    parts = []
    if filters.get("seat") is not None:
        parts.append(f"seat={filters['seat']}")
    if filters.get("origin") is not None:
        parts.append(f"origin={filters['origin']}")
    parts.append(f"min_plays={filters.get('min_plays', 0)}")
    return ", ".join(parts) if parts else "no filters"


def _fmt_pct(v) -> str:
    return f"{100.0 * v:>6.1f}%" if v is not None else f"{'—':>7}"


def _fmt_num(v, width: int = 6, prec: int = 1) -> str:
    return f"{v:>{width}.{prec}f}" if v is not None else f"{'—':>{width}}"


def _resolve_reverse(sort_key: str, desc: bool | None) -> bool:
    _, default_desc = _SORT_FIELDS[sort_key]
    return default_desc if desc is None else desc


def _sort_rows(rows: list[dict], sort_key: str, desc: bool | None) -> list[dict]:
    field, _ = _SORT_FIELDS[sort_key]
    reverse = _resolve_reverse(sort_key, desc)
    if field == "card_def_id":
        return sorted(rows, key=lambda r: r[field], reverse=reverse)
    rows_with = [r for r in rows if r[field] is not None]
    rows_without = [r for r in rows if r[field] is None]
    rows_with.sort(key=lambda r: r[field], reverse=reverse)
    return rows_with + rows_without


def render(data: dict, sort_key: str, desc: bool | None, min_plays: int) -> str:
    games_total = data["games_total"]
    all_cards = data["cards"]
    filt = _filter_summary({**data.get("filters", {}), "min_plays": min_plays})
    if data.get("no_table"):
        return ("No 'card_events' table in this database yet.\n"
                "  The agent server creates it on startup (CREATE TABLE IF NOT "
                "EXISTS). Restart the server, then play or run self-play to "
                "populate it.")
    if not all_cards:
        return (f"No card events match [{filt}] "
                "(is the DB populated / filters too strict?).")

    cards = [c for c in all_cards if c["played"] >= min_plays]
    low_sample = [c for c in all_cards if c["played"] < min_plays]
    cards = _sort_rows(cards, sort_key, desc)
    low_sample = _sort_rows(low_sample, sort_key, desc)

    name_w = max(len("Card"), max(len(c["card_def_id"]) for c in all_cards))

    out: list[str] = []
    out.append("")
    out.append(_bold(f"  Per-card statistics — {games_total} games, "
                     f"{len(all_cards)} distinct cards"))
    base_wr = data.get("base_win_rate")
    if base_wr is not None:
        out.append(_dim(f"  base win rate: {100.0 * base_wr:.1f}%"))
    out.append(_dim(f"  filters: {filt}"))
    out.append(_dim(f"  sorted by {sort_key}"
                    f"{' desc' if _resolve_reverse(sort_key, desc) else ' asc'}"))
    out.append("")

    header = (f"  {'Card':<{name_w}}  {'Seen':>4}  {'Plyd':>4}  {'Draw%':>7}  "
              f"{'Play%':>7}  {'P|Drw':>7}  {'Mull%':>7}  {'Stuck%':>7}  "
              f"{'AvgT':>6}  {'AvgE':>6}  {'Died':>4}  {'WR|Pl':>7}")
    out.append(_bold(header))
    out.append(_dim("  " + "─" * (len(header) - 2)))

    def _emit(card_rows: list[dict]) -> None:
        for c in card_rows:
            wr = c["win_rate_when_played"]
            wr_txt = _fmt_pct(wr)
            if wr is not None and base_wr is not None:
                if wr > base_wr + 1e-9:
                    wr_txt = _green(wr_txt)
                elif wr < base_wr - 1e-9:
                    wr_txt = _red(wr_txt)
            line = (
                f"  {c['card_def_id']:<{name_w}}  "
                f"{c['games_seen']:>4}  {c['played']:>4}  "
                f"{_fmt_pct(c['draw_rate'])}  {_fmt_pct(c['play_rate'])}  "
                f"{_fmt_pct(c['play_when_drawn_rate'])}  "
                f"{_fmt_pct(c['mulligan_rate'])}  {_fmt_pct(c['stuck_in_hand_rate'])}  "
                f"{_fmt_num(c['avg_turn_played'])}  {_fmt_num(c['avg_energy_spent'])}  "
                f"{c['deaths']:>4}  {wr_txt}"
            )
            out.append(line)

    _emit(cards)
    if low_sample:
        out.append("")
        out.append(_dim(f"  Low sample (< {min_plays} plays) — interpret with caution"))
        out.append(_dim("  " + "─" * (len(header) - 2)))
        _emit(low_sample)

    out.append("")
    out.append(_dim("  WPA omitted (needs turn_snapshots). WR|Pl is "
                    "survivorship-biased — see doc §3 caveats."))
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Per-card statistics report.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH,
                        help=f"SQLite DB path (default: {DEFAULT_DB_PATH})")
    parser.add_argument("--sort", choices=sorted(_SORT_FIELDS), default="played",
                        help="Sort column (default: played)")
    parser.add_argument("--desc", dest="desc", action="store_true", default=None,
                        help="Force descending sort")
    parser.add_argument("--asc", dest="desc", action="store_false",
                        help="Force ascending sort")
    parser.add_argument("--seat", type=int,
                        help="Filter by reporting seat (my_player_index, 0 or 1)")
    parser.add_argument("--origin",
                        help="Filter by game origin (self_play|vs_human|vs_heuristic)")
    parser.add_argument("--min-plays", type=int, default=20, dest="min_plays",
                        help="Cards below N plays go to a low-sample section (default: 20)")
    args = parser.parse_args(argv)

    filters = {"seat": args.seat, "origin": args.origin}
    conn = _connect(args.db)
    try:
        data = gather(conn, filters=filters)
    finally:
        conn.close()
    print(render(data, args.sort, args.desc, args.min_plays))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
