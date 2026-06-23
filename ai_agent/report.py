#!/usr/bin/env python3
"""AI agent performance report.

Reads the evaluation telemetry stored by the agent service (see ``memory.py``)
and renders a readable scorecard in the terminal: reliability metrics, engine
acceptance, latency distribution, per-game breakdown, and human-feedback rubric
scores. Optionally writes PNG charts when ``matplotlib`` is installed.

Usage:
    python -m ai_agent.report                 # read default DB, print to console
    python ai_agent/report.py --db other.db   # point at a specific database
    python ai_agent/report.py --charts out/   # also save PNG charts to out/
    python ai_agent/report.py --json          # emit raw aggregate JSON only

The script only depends on the standard library for its console output. PNG
charts require ``matplotlib`` (``pip install matplotlib``); without it, the
``--charts`` flag is skipped with a notice.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = Path(__file__).parent / "agent_memory.db"

# ── ANSI styling (auto-disabled when output is not a TTY) ──────────────────────
import sys

_USE_COLOR = sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def _bold(t: str) -> str:
    return _c(t, "1")


def _dim(t: str) -> str:
    return _c(t, "2")


def _green(t: str) -> str:
    return _c(t, "32")


def _yellow(t: str) -> str:
    return _c(t, "33")


def _red(t: str) -> str:
    return _c(t, "31")


def _cyan(t: str) -> str:
    return _c(t, "36")


def _rule(width: int = 64) -> str:
    return _dim("-" * width)


def _header(title: str) -> str:
    return f"\n{_bold(_cyan(title))}\n{_rule()}"


# ── Data access ────────────────────────────────────────────────────────────────
def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(
            f"No telemetry database found at {db_path}. "
            "Play some Player-vs-AI games first so the agent records metrics."
        )
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _percentile(sorted_values: list[float], pct: int) -> float:
    if not sorted_values:
        return 0.0
    k = max(0, min(len(sorted_values) - 1, round((pct / 100.0) * len(sorted_values) + 0.5) - 1))
    return float(sorted_values[k])


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> sqlite3.Row:
    return conn.execute(sql, params).fetchone()


def gather(conn: sqlite3.Connection) -> dict:
    """Pull all telemetry into a single dict of aggregates + per-game rows."""
    server = _scalar(
        conn,
        "SELECT COUNT(*) AS n, "
        "COALESCE(SUM(model_calls),0) AS calls, "
        "COALESCE(AVG(latency_ms),0) AS avg_lat, "
        "COALESCE(SUM(parse_retries),0) AS parse_r, "
        "COALESCE(SUM(legality_retries),0) AS legal_r, "
        "COALESCE(SUM(fell_back_to_pass),0) AS fallbacks, "
        "COALESCE(AVG(tool_rounds),0) AS avg_tools "
        "FROM decision_eval_metrics",
    )
    client = _scalar(
        conn,
        "SELECT COUNT(*) AS n, "
        "COALESCE(AVG(latency_ms),0) AS avg_lat, "
        "COALESCE(SUM(rejection_retries),0) AS rej, "
        "COALESCE(SUM(heuristic_fallback),0) AS heur, "
        "COALESCE(SUM(CASE WHEN accepted=1 THEN 1 ELSE 0 END),0) AS accepted, "
        "COALESCE(SUM(CASE WHEN accepted IS NOT NULL THEN 1 ELSE 0 END),0) AS resolved "
        "FROM client_decision_metrics",
    )
    latencies = [r["latency_ms"] for r in conn.execute(
        "SELECT latency_ms FROM decision_eval_metrics ORDER BY latency_ms"
    ).fetchall()]
    hf = _scalar(
        conn,
        "SELECT COUNT(*) AS n, AVG(strategic) AS strategic, AVG(tactical) AS tactical, "
        "AVG(resource) AS resource, AVG(rules) AS rules, AVG(overall) AS overall "
        "FROM human_feedback",
    )
    mf = _scalar(
        conn,
        "SELECT COUNT(*) AS n, "
        "COALESCE(SUM(CASE WHEN sentiment='like' THEN 1 ELSE 0 END),0) AS likes, "
        "COALESCE(SUM(CASE WHEN sentiment='neutral' THEN 1 ELSE 0 END),0) AS neutrals, "
        "COALESCE(SUM(CASE WHEN sentiment='dislike' THEN 1 ELSE 0 END),0) AS dislikes "
        "FROM move_feedback",
    )
    games = _scalar(
        conn,
        "SELECT COUNT(*) AS n, "
        "COALESCE(SUM(CASE WHEN outcome='win' THEN 1 ELSE 0 END),0) AS wins, "
        "COALESCE(SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END),0) AS losses, "
        "COALESCE(SUM(CASE WHEN outcome='draw' THEN 1 ELSE 0 END),0) AS draws, "
        "COALESCE(AVG(turns_played),0) AS avg_turns "
        "FROM games",
    )

    per_decision_type = conn.execute(
        "SELECT decision_type, COUNT(*) AS n, AVG(latency_ms) AS avg_lat, "
        "SUM(legality_retries) AS legal_r, SUM(fell_back_to_pass) AS fb "
        "FROM decision_eval_metrics GROUP BY decision_type ORDER BY n DESC"
    ).fetchall()

    per_game = conn.execute(
        "SELECT s.game_id, s.decisions, s.model_calls_total, s.avg_latency_ms, "
        "s.p95_latency_ms, s.parse_retry_total, s.legality_retry_total, s.fallback_count, "
        "g.outcome, g.my_score, g.opp_score, g.turns_played "
        "FROM game_eval_summary s LEFT JOIN games g ON g.game_id = s.game_id "
        "ORDER BY s.timestamp DESC"
    ).fetchall()

    tags = conn.execute(
        "SELECT tags FROM human_feedback WHERE tags IS NOT NULL AND tags != ''"
    ).fetchall()

    recent_notes = conn.execute(
        "SELECT game_id, overall, note FROM human_feedback "
        "WHERE note IS NOT NULL AND note != '' ORDER BY timestamp DESC LIMIT 5"
    ).fetchall()

    disliked_moves = conn.execute(
        "SELECT turn, move_desc FROM move_feedback WHERE sentiment='dislike' "
        "AND move_desc IS NOT NULL AND move_desc != '' ORDER BY timestamp DESC LIMIT 5"
    ).fetchall()

    return {
        "server": server,
        "client": client,
        "latencies": latencies,
        "hf": hf,
        "mf": mf,
        "disliked_moves": disliked_moves,
        "games": games,
        "per_decision_type": per_decision_type,
        "per_game": per_game,
        "tags": tags,
        "recent_notes": recent_notes,
    }


# ── Rendering helpers ──────────────────────────────────────────────────────────
def _bar(value: float, maximum: float, width: int = 28, color=_green) -> str:
    if maximum <= 0:
        filled = 0
    else:
        filled = int(round((value / maximum) * width))
    filled = max(0, min(width, filled))
    return color("#" * filled) + _dim("." * (width - filled))


def _score_bar(value: Optional[float], width: int = 20) -> str:
    """Render a 1-5 rubric score as a bar."""
    if value is None:
        return _dim("no data")
    color = _green if value >= 4 else _yellow if value >= 2.5 else _red
    filled = int(round((value / 5.0) * width))
    bar = color("#" * filled) + _dim("." * (width - filled))
    return f"{bar} {_bold(f'{value:.2f}')}/5"


def _fmt_pct(num: int, den: int) -> str:
    if den <= 0:
        return _dim("n/a")
    pct = 100.0 * num / den
    color = _green if pct >= 90 else _yellow if pct >= 70 else _red
    return color(f"{pct:.1f}%")


def render(data: dict) -> str:
    out: list[str] = []
    s = data["server"]
    c = data["client"]
    g = data["games"]
    hf = data["hf"]
    lats = data["latencies"]

    out.append(_bold(_cyan("\n" + "=" * 56)))
    out.append(_bold(_cyan("        AI AGENT PERFORMANCE SCORECARD")))
    out.append(_bold(_cyan("=" * 56)))

    # ── Games / strength ──
    out.append(_header("Game Outcomes"))
    n_games = g["n"]
    if n_games:
        wr = _fmt_pct(g["wins"], n_games)
        out.append(f"  Games played      {_bold(str(n_games))}")
        out.append(f"  Win / Loss / Draw {_green(str(g['wins']))} / {_red(str(g['losses']))} / {_yellow(str(g['draws']))}")
        out.append(f"  Win rate          {wr}")
        out.append(f"  Avg turns/game    {g['avg_turns']:.1f}")
    else:
        out.append(_dim("  No completed games recorded yet."))

    # ── Server-side reliability ──
    out.append(_header("Server-Side Reliability (agent internals)"))
    n = s["n"]
    if n:
        avg_calls = s["calls"] / n
        out.append(f"  Decisions produced  {_bold(str(n))}")
        out.append(f"  Avg model calls     {avg_calls:.2f}   {_bar(avg_calls, max(avg_calls, 3))}")
        out.append(f"  Avg tool rounds     {s['avg_tools']:.2f}")
        out.append(f"  Parse retries       {_yellow(str(s['parse_r'])) if s['parse_r'] else '0'}")
        out.append(f"  Legality retries    {_yellow(str(s['legal_r'])) if s['legal_r'] else '0'}")
        fb = s["fallbacks"]
        fb_str = _red(str(fb)) if fb else _green("0")
        out.append(f"  Fallback passes     {fb_str}   {_dim(f'({_safe_pct(fb, n)} of decisions)')}")
    else:
        out.append(_dim("  No server-side decision metrics recorded yet."))

    # ── Latency distribution ──
    if lats:
        out.append(_header("Latency Distribution (ms)"))
        p50 = _percentile(lats, 50)
        p95 = _percentile(lats, 95)
        p99 = _percentile(lats, 99)
        mx = max(lats)
        out.append(f"  min   {min(lats):6.0f}  {_bar(min(lats), mx)}")
        out.append(f"  p50   {p50:6.0f}  {_bar(p50, mx)}")
        out.append(f"  p95   {p95:6.0f}  {_bar(p95, mx, color=_yellow)}")
        out.append(f"  p99   {p99:6.0f}  {_bar(p99, mx, color=_red)}")
        out.append(f"  max   {mx:6.0f}  {_bar(mx, mx, color=_red)}")
        out.append(_histogram(lats))

    # ── Engine-observed ──
    out.append(_header("Engine-Observed (as the game sees the AI)"))
    if c["n"]:
        out.append(f"  Decisions seen      {_bold(str(c['n']))}")
        out.append(f"  Avg latency         {c['avg_lat']:.0f} ms")
        out.append(f"  Acceptance rate     {_fmt_pct(c['accepted'], c['resolved'])}  {_dim(f'({c['accepted']}/{c['resolved']} resolved)')}")
        out.append(f"  Rejection retries   {_yellow(str(c['rej'])) if c['rej'] else '0'}")
        hh = c["heur"]
        out.append(f"  Heuristic fallbacks {_red(str(hh)) if hh else _green('0')}")
    else:
        out.append(_dim("  No engine-observed metrics recorded yet."))

    # ── Per decision type ──
    if data["per_decision_type"]:
        out.append(_header("By Decision Type"))
        out.append(_dim(f"  {'type':<22}{'count':>7}{'avg ms':>9}{'legal-r':>9}{'fallbk':>8}"))
        for r in data["per_decision_type"]:
            out.append(
                f"  {str(r['decision_type'])[:22]:<22}{r['n']:>7}{r['avg_lat']:>9.0f}"
                f"{r['legal_r'] or 0:>9}{r['fb'] or 0:>8}"
            )

    # ── Human feedback ──
    out.append(_header("Human Feedback (rubric, 1-5)"))
    if hf["n"]:
        out.append(f"  Submissions: {_bold(str(hf['n']))}")
        out.append(f"  Strategic   {_score_bar(hf['strategic'])}")
        out.append(f"  Tactical    {_score_bar(hf['tactical'])}")
        out.append(f"  Resource    {_score_bar(hf['resource'])}")
        out.append(f"  Rules       {_score_bar(hf['rules'])}")
        out.append(f"  Overall     {_score_bar(hf['overall'])}")
        tag_counts = _count_tags(data["tags"])
        if tag_counts:
            out.append(_dim("  Tags:"))
            for tag, cnt in tag_counts:
                out.append(f"    {tag:<22}{_bar(cnt, tag_counts[0][1], width=18)} {cnt}")
        if data["recent_notes"]:
            out.append(_dim("  Recent notes:"))
            for note in data["recent_notes"]:
                score = f"[{note['overall']}/5] " if note["overall"] is not None else ""
                out.append(f"    {_dim('-')} {score}{note['note'][:70]}")
    else:
        out.append(_dim("  No human feedback submitted yet. Enable the toggle in the Main Menu."))

    # ── Per-move sentiment ──
    mf = data["mf"]
    out.append(_header("Live Per-Move Feedback (thumbs)"))
    if mf["n"]:
        total = mf["n"]
        out.append(f"  Rated moves: {_bold(str(total))}  {_dim('(ignored moves are not counted)')}")
        out.append(f"  Like     {_bar(mf['likes'], total, width=24, color=_green)} {mf['likes']}  ({_safe_pct(mf['likes'], total)})")
        out.append(f"  Neutral  {_bar(mf['neutrals'], total, width=24, color=_yellow)} {mf['neutrals']}  ({_safe_pct(mf['neutrals'], total)})")
        out.append(f"  Dislike  {_bar(mf['dislikes'], total, width=24, color=_red)} {mf['dislikes']}  ({_safe_pct(mf['dislikes'], total)})")
        if data["disliked_moves"]:
            out.append(_dim("  Recent disliked moves:"))
            for m in data["disliked_moves"]:
                turn = f"T{m['turn']} " if m["turn"] is not None else ""
                out.append(f"    {_dim('-')} {turn}{m['move_desc'][:60]}")
    else:
        out.append(_dim("  No per-move feedback yet. Enable Human AI Evaluation in the Main Menu."))

    # ── Per-game table ──
    if data["per_game"]:
        out.append(_header("Per-Game Breakdown"))
        out.append(_dim(
            f"  {'game_id':<16}{'res':>5}{'score':>7}{'dec':>5}{'calls':>7}"
            f"{'avg ms':>8}{'p95':>7}{'fb':>4}"
        ))
        for r in data["per_game"]:
            outcome = r["outcome"] or "?"
            oc = _green("W") if outcome == "win" else _red("L") if outcome == "loss" else _yellow(outcome[:1].upper() if outcome != "?" else "?")
            score = f"{r['my_score']}-{r['opp_score']}" if r["my_score"] is not None else "-"
            out.append(
                f"  {str(r['game_id'])[:16]:<16}{oc:>5}{score:>7}{r['decisions']:>5}"
                f"{r['model_calls_total']:>7}{r['avg_latency_ms']:>8.0f}{r['p95_latency_ms']:>7}"
                f"{r['fallback_count']:>4}"
            )

    out.append("")
    return "\n".join(out)


def _safe_pct(num: int, den: int) -> str:
    return f"{100.0 * num / den:.1f}%" if den else "0%"


def _count_tags(rows) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for row in rows:
        try:
            tags = json.loads(row["tags"])
        except (json.JSONDecodeError, TypeError):
            continue
        for t in tags or []:
            counts[t] = counts.get(t, 0) + 1
    return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)


def _histogram(values: list[float], bins: int = 10, width: int = 30) -> str:
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if hi == lo:
        return _dim(f"  all {len(values)} samples ~ {lo:.0f} ms")
    span = hi - lo
    counts = [0] * bins
    for v in values:
        idx = min(bins - 1, int((v - lo) / span * bins))
        counts[idx] += 1
    peak = max(counts) or 1
    lines = [_dim("  histogram:")]
    for i, cnt in enumerate(counts):
        edge = lo + (span * i / bins)
        bar = _cyan("#" * int(round(cnt / peak * width)))
        lines.append(f"  {edge:6.0f} | {bar} {_dim(str(cnt))}")
    return "\n".join(lines)


# ── Optional PNG charts ────────────────────────────────────────────────────────
def write_charts(data: dict, out_dir: Path) -> list[Path]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(_yellow("matplotlib not installed - skipping PNG charts. "
                      "Run `pip install matplotlib` to enable."))
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # 1. Latency histogram
    lats = data["latencies"]
    if lats:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.hist(lats, bins=20, color="#3b82f6", edgecolor="white")
        ax.set_title("Decision Latency Distribution")
        ax.set_xlabel("latency (ms)")
        ax.set_ylabel("decisions")
        p = out_dir / "latency_hist.png"
        fig.tight_layout()
        fig.savefig(p, dpi=120)
        plt.close(fig)
        written.append(p)

    # 2. Human-feedback rubric radar/bar
    hf = data["hf"]
    if hf["n"]:
        labels = ["strategic", "tactical", "resource", "rules", "overall"]
        vals = [hf[k] or 0 for k in labels]
        fig, ax = plt.subplots(figsize=(7, 4))
        colors = ["#22c55e" if v >= 4 else "#eab308" if v >= 2.5 else "#ef4444" for v in vals]
        ax.bar(labels, vals, color=colors)
        ax.set_ylim(0, 5)
        ax.set_title(f"Human Feedback Rubric (n={hf['n']})")
        ax.set_ylabel("avg score (1-5)")
        for i, v in enumerate(vals):
            ax.text(i, v + 0.1, f"{v:.1f}", ha="center")
        p = out_dir / "human_rubric.png"
        fig.tight_layout()
        fig.savefig(p, dpi=120)
        plt.close(fig)
        written.append(p)

    # 3. Win/Loss/Draw pie
    g = data["games"]
    if g["n"]:
        fig, ax = plt.subplots(figsize=(5, 5))
        parts = [g["wins"], g["losses"], g["draws"]]
        plabels = ["Win", "Loss", "Draw"]
        pcolors = ["#22c55e", "#ef4444", "#eab308"]
        nz = [(l, v, col) for l, v, col in zip(plabels, parts, pcolors) if v > 0]
        if nz:
            ax.pie([v for _, v, _ in nz], labels=[l for l, _, _ in nz],
                   colors=[col for _, _, col in nz], autopct="%1.0f%%", startangle=90)
            ax.set_title(f"Game Outcomes (n={g['n']})")
            p = out_dir / "outcomes_pie.png"
            fig.tight_layout()
            fig.savefig(p, dpi=120)
            plt.close(fig)
            written.append(p)

    # 4. Per-game latency trend
    pg = list(reversed(data["per_game"]))
    if len(pg) >= 2:
        fig, ax = plt.subplots(figsize=(9, 4))
        xs = list(range(len(pg)))
        ax.plot(xs, [r["avg_latency_ms"] for r in pg], marker="o", label="avg ms", color="#3b82f6")
        ax.plot(xs, [r["p95_latency_ms"] for r in pg], marker="s", label="p95 ms", color="#ef4444")
        ax.set_title("Latency Trend by Game")
        ax.set_xlabel("game (oldest -> newest)")
        ax.set_ylabel("latency (ms)")
        ax.legend()
        p = out_dir / "latency_trend.png"
        fig.tight_layout()
        fig.savefig(p, dpi=120)
        plt.close(fig)
        written.append(p)

    # 5. Per-move sentiment pie
    mf = data["mf"]
    if mf["n"]:
        fig, ax = plt.subplots(figsize=(5, 5))
        parts = [mf["likes"], mf["neutrals"], mf["dislikes"]]
        plabels = ["Like", "Neutral", "Dislike"]
        pcolors = ["#22c55e", "#eab308", "#ef4444"]
        nz = [(l, v, col) for l, v, col in zip(plabels, parts, pcolors) if v > 0]
        if nz:
            ax.pie([v for _, v, _ in nz], labels=[l for l, _, _ in nz],
                   colors=[col for _, _, col in nz], autopct="%1.0f%%", startangle=90)
            ax.set_title(f"Per-Move Sentiment (n={mf['n']})")
            p = out_dir / "move_sentiment_pie.png"
            fig.tight_layout()
            fig.savefig(p, dpi=120)
            plt.close(fig)
            written.append(p)

    return written


def _aggregate_json(data: dict) -> dict:
    s, c, g, hf = data["server"], data["client"], data["games"], data["hf"]
    mf = data["mf"]
    lats = data["latencies"]
    n = s["n"]
    return {
        "games": {
            "played": g["n"], "wins": g["wins"], "losses": g["losses"],
            "draws": g["draws"], "win_rate": round(g["wins"] / g["n"], 3) if g["n"] else None,
            "avg_turns": round(g["avg_turns"], 1),
        },
        "server_side": {
            "decisions": n,
            "avg_model_calls": round(s["calls"] / n, 2) if n else 0,
            "avg_latency_ms": round(s["avg_lat"], 1),
            "p50_latency_ms": _percentile(lats, 50),
            "p95_latency_ms": _percentile(lats, 95),
            "parse_retries": s["parse_r"],
            "legality_retries": s["legal_r"],
            "fallback_passes": s["fallbacks"],
        },
        "engine_observed": {
            "decisions": c["n"],
            "avg_latency_ms": round(c["avg_lat"], 1),
            "acceptance_rate": round(c["accepted"] / c["resolved"], 3) if c["resolved"] else None,
            "rejection_retries": c["rej"],
            "heuristic_fallbacks": c["heur"],
        },
        "human_feedback": {
            "submissions": hf["n"],
            "avg_strategic": round(hf["strategic"], 2) if hf["strategic"] is not None else None,
            "avg_tactical": round(hf["tactical"], 2) if hf["tactical"] is not None else None,
            "avg_resource": round(hf["resource"], 2) if hf["resource"] is not None else None,
            "avg_rules": round(hf["rules"], 2) if hf["rules"] is not None else None,
            "avg_overall": round(hf["overall"], 2) if hf["overall"] is not None else None,
        },
        "move_feedback": {
            "submissions": mf["n"],
            "likes": mf["likes"],
            "neutrals": mf["neutrals"],
            "dislikes": mf["dislikes"],
            "like_rate": round(mf["likes"] / mf["n"], 3) if mf["n"] else None,
        },
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Render the AI agent performance scorecard.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH,
                        help=f"Path to the telemetry SQLite DB (default: {DEFAULT_DB_PATH}).")
    parser.add_argument("--charts", type=Path, metavar="DIR",
                        help="Directory to write PNG charts (requires matplotlib).")
    parser.add_argument("--json", action="store_true",
                        help="Print aggregate metrics as JSON instead of the console scorecard.")
    args = parser.parse_args(argv)

    try:
        conn = _connect(args.db)
    except FileNotFoundError as exc:
        print(_red(str(exc)))
        return 1

    try:
        data = gather(conn)
    finally:
        conn.close()

    if args.json:
        print(json.dumps(_aggregate_json(data), indent=2))
        return 0

    print(render(data))

    if args.charts:
        written = write_charts(data, args.charts)
        if written:
            print(_green(f"\nSaved {len(written)} chart(s) to {args.charts}:"))
            for p in written:
                print(f"  {p}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
