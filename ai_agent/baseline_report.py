"""
Reasoner Multi-Game Baseline Report Generator

Extracts commit rate, fallback rate, and hash diverge rate from a multi-game
baseline run and generates summary reports. Run after a Reasoner-enabled
self-play session to archive operational reliability metrics.

Usage:
    python -m ai_agent.baseline_report \\
      --db ai_agent/reasoner_baseline.db \\
      --log agent_search.log \\
      --out Data/AI/Baseline/reasoner-multi-game-2026-09-27/baseline_summary.json \\
      [--markdown Data/AI/Baseline/reasoner-multi-game-2026-09-27/summary.md]

See ai_agent/docs/Reasoner_Multi_Game_Baseline_Plan.md for definitions.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def compute_commit_rate(db_path: str) -> dict[str, Any]:
    """
    Compute commit rate from reasoner_decisions table.
    
    Returns:
        {
            "eligible_turns": N,
            "commit_count": M,
            "commit_rate": M/N,
            "line_source_breakdown": {...}
        }
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Count all reasoner decisions (eligible turns)
    cur.execute("""
        SELECT COUNT(*) as total
        FROM reasoner_decisions
        WHERE terminal_kind IS NOT NULL
    """)
    total = cur.fetchone()["total"]
    
    # Count committed lines (terminal_kind = 'line' and committed = 1)
    cur.execute("""
        SELECT COUNT(*) as commits
        FROM reasoner_decisions
        WHERE terminal_kind = 'line' AND committed = 1
    """)
    commits = cur.fetchone()["commits"]
    
    # Get source breakdown from selected_source_lineage_json
    cur.execute("""
        SELECT selected_source_lineage_json
        FROM reasoner_decisions
        WHERE terminal_kind = 'line' AND committed = 1
          AND selected_source_lineage_json IS NOT NULL
    """)
    sources = Counter()
    for row in cur:
        try:
            lineage = json.loads(row["selected_source_lineage_json"])
            if lineage and len(lineage) > 0:
                # Use the first (most specific) source
                source = lineage[0] if isinstance(lineage, list) else str(lineage)
                sources[source] += 1
        except (json.JSONDecodeError, TypeError):
            sources["unknown"] += 1
    
    conn.close()
    
    commit_rate = commits / total if total > 0 else 0.0
    
    return {
        "eligible_turns": total,
        "commit_count": commits,
        "commit_rate": commit_rate,
        "line_source_breakdown": dict(sources),
    }


def compute_fallback_rate(db_path: str) -> dict[str, Any]:
    """
    Compute fallback rate from reasoner_decisions table.
    
    Returns:
        {
            "fallback_count": K,
            "fallback_rate": K/N,
            "breakdown": {...}
        }
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Count eligible turns
    cur.execute("""
        SELECT COUNT(*) as total
        FROM reasoner_decisions
        WHERE terminal_kind IS NOT NULL
    """)
    total = cur.fetchone()["total"]
    
    # Count fallbacks (terminal_kind = 'base_search_fallback')
    cur.execute("""
        SELECT COUNT(*) as fallbacks
        FROM reasoner_decisions
        WHERE terminal_kind = 'base_search_fallback'
    """)
    fallbacks = cur.fetchone()["fallbacks"]
    
    # Get fallback reason breakdown
    cur.execute("""
        SELECT fallback_reason, COUNT(*) as count
        FROM reasoner_decisions
        WHERE terminal_kind = 'base_search_fallback'
          AND fallback_reason IS NOT NULL
        GROUP BY fallback_reason
    """)
    breakdown = {}
    for row in cur:
        reason = row["fallback_reason"]
        # Normalize reason from verbose rationale to short enum
        if "missing root" in reason.lower() or "missing_root" in reason.lower():
            key = "missing_root_hash"
        elif "budget" in reason.lower() or "exhausted" in reason.lower():
            key = "budget_exhausted"
        elif "api" in reason.lower() or "transient" in reason.lower() or "failure" in reason.lower():
            key = "api_failure_after_retries"
        elif "retry" in reason.lower():
            key = "terminal_retries_exhausted"
        elif "validation" in reason.lower():
            key = "terminal_validation_failed"
        elif "unreachable" in reason.lower():
            key = "engine_unreachable"
        else:
            key = "other"
        breakdown[key] = breakdown.get(key, 0) + row["count"]
    
    conn.close()
    
    fallback_rate = fallbacks / total if total > 0 else 0.0
    
    return {
        "fallback_count": fallbacks,
        "fallback_rate": fallback_rate,
        "breakdown": breakdown,
    }


def compute_hash_diverge_rate(db_path: str, log_path: str | None = None) -> dict[str, Any]:
    """
    Compute hash divergence rate from database and optionally logs.
    
    Hash divergence happens when:
    1. root_state_hash mismatch before step 0
    2. expected_pre_hash mismatch mid-line
    
    Currently we don't have a dedicated divergences table, so we infer from:
    - Committed lines where the line was abandoned (no explicit tracking yet)
    - Log entries mentioning hash mismatches (if log_path provided)
    
    Returns:
        {
            "diverge_count": D,
            "committed_lines_attempted": L,
            "diverge_rate": D/L,
            "breakdown": {"root_mismatch": ..., "pre_hash_mismatch": ...}
        }
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Count committed lines attempted (terminal_kind = 'line' and committed = 1)
    cur.execute("""
        SELECT COUNT(*) as committed_lines
        FROM reasoner_decisions
        WHERE terminal_kind = 'line' AND committed = 1
    """)
    committed_lines = cur.fetchone()["committed_lines"]
    
    conn.close()
    
    # Parse logs for hash divergence events if log provided
    diverge_count = 0
    root_mismatch = 0
    pre_hash_mismatch = 0
    
    if log_path and Path(log_path).exists():
        with open(log_path, "r") as f:
            for line in f:
                # Look for hash mismatch patterns in logs
                if "root_state_hash" in line.lower() and ("mismatch" in line.lower() or "differ" in line.lower()):
                    root_mismatch += 1
                    diverge_count += 1
                elif "expected_pre_hash" in line.lower() and ("mismatch" in line.lower() or "differ" in line.lower()):
                    pre_hash_mismatch += 1
                    diverge_count += 1
                elif "hash diverge" in line.lower() or "diverged" in line.lower():
                    # Generic divergence mention
                    if "root" in line.lower():
                        root_mismatch += 1
                    else:
                        pre_hash_mismatch += 1
                    diverge_count += 1
    
    diverge_rate = diverge_count / committed_lines if committed_lines > 0 else 0.0
    
    return {
        "diverge_count": diverge_count,
        "committed_lines_attempted": committed_lines,
        "diverge_rate": diverge_rate,
        "breakdown": {
            "root_mismatch_pre_step_0": root_mismatch,
            "pre_hash_mismatch_mid_line": pre_hash_mismatch,
        },
    }


def compute_exemptions(db_path: str) -> dict[str, int]:
    """
    Count exemptions (turns not eligible for Reasoner).
    
    Currently we track investigation_exemption in reasoner_decisions.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    cur.execute("""
        SELECT investigation_exemption, COUNT(*) as count
        FROM reasoner_decisions
        WHERE investigation_exemption IS NOT NULL
        GROUP BY investigation_exemption
    """)
    
    exemptions = {}
    for row in cur:
        exemptions[row["investigation_exemption"]] = row["count"]
    
    conn.close()
    
    return exemptions


def get_tool_usage(db_path: str) -> dict[str, Any]:
    """Extract tool usage statistics from reasoner_decisions."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    cur.execute("""
        SELECT tool_mix_json, model_calls
        FROM reasoner_decisions
        WHERE tool_mix_json IS NOT NULL
    """)
    
    tool_counts = Counter()
    total_tool_calls = 0
    total_model_calls = 0
    
    for row in cur:
        try:
            tool_mix = json.loads(row["tool_mix_json"])
            for tool, count in tool_mix.items():
                tool_counts[tool] += count
                total_tool_calls += count
        except (json.JSONDecodeError, TypeError):
            pass
        if row["model_calls"]:
            total_model_calls += row["model_calls"]
    
    conn.close()
    
    return {
        "total_tool_calls": total_tool_calls,
        "total_model_calls": total_model_calls,
        "tool_breakdown": dict(tool_counts),
    }


def get_latency_stats(db_path: str) -> dict[str, Any]:
    """Extract latency statistics from reasoner_decisions."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    cur.execute("""
        SELECT reasoner_latency_ms, engine_latency_ms
        FROM reasoner_decisions
        WHERE reasoner_latency_ms IS NOT NULL
        ORDER BY reasoner_latency_ms
    """)
    
    latencies = [row["reasoner_latency_ms"] for row in cur if row["reasoner_latency_ms"]]
    
    if not latencies:
        return {"median_ms": 0, "p95_ms": 0, "count": 0}
    
    count = len(latencies)
    median_idx = count // 2
    p95_idx = int(count * 0.95)
    
    conn.close()
    
    return {
        "median_ms": latencies[median_idx] if count > 0 else 0,
        "p95_ms": latencies[p95_idx] if count > 0 else 0,
        "count": count,
    }


def get_game_stats(db_path: str) -> dict[str, Any]:
    """Extract game-level statistics."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Count distinct games
    cur.execute("""
        SELECT COUNT(DISTINCT game_id) as game_count
        FROM reasoner_decisions
    """)
    game_count = cur.fetchone()["game_count"]
    
    # Count total turns per game and average
    cur.execute("""
        SELECT game_id, MAX(turn) as max_turn
        FROM reasoner_decisions
        GROUP BY game_id
    """)
    
    turns = [row["max_turn"] for row in cur if row["max_turn"]]
    avg_turns = sum(turns) / len(turns) if turns else 0
    
    # Count total decisions
    cur.execute("""
        SELECT COUNT(*) as total
        FROM reasoner_decisions
    """)
    total_decisions = cur.fetchone()["total"]
    
    conn.close()
    
    return {
        "games_completed": game_count,
        "total_turns": sum(turns) if turns else 0,
        "average_turns_per_game": avg_turns,
        "total_decisions": total_decisions,
    }


def generate_baseline_summary(
    db_path: str,
    log_path: str | None = None,
    git_sha: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Generate complete baseline summary from database and logs.
    
    Args:
        db_path: Path to the SQLite database
        log_path: Optional path to agent_search.log
        git_sha: Git commit SHA for this run
        model: Model identifier (e.g. 'gpt-4o')
    
    Returns:
        Complete baseline_summary.json dictionary
    """
    commit = compute_commit_rate(db_path)
    fallback = compute_fallback_rate(db_path)
    diverge = compute_hash_diverge_rate(db_path, log_path)
    exemptions = compute_exemptions(db_path)
    tool_usage = get_tool_usage(db_path)
    latency = get_latency_stats(db_path)
    games = get_game_stats(db_path)
    
    return {
        "run_date": datetime.now().strftime("%Y-%m-%d"),
        "git_sha": git_sha or "unknown",
        "model": model or "unknown",
        "games_completed": games["games_completed"],
        "total_turns": games["total_turns"],
        "average_turns_per_game": round(games["average_turns_per_game"], 1),
        "total_decisions": games["total_decisions"],
        "eligible_reasoner_turns": commit["eligible_turns"],
        "exemptions": exemptions,
        "commit_count": commit["commit_count"],
        "commit_rate": round(commit["commit_rate"], 3),
        "line_source_breakdown": commit["line_source_breakdown"],
        "fallback_count": fallback["fallback_count"],
        "fallback_rate": round(fallback["fallback_rate"], 3),
        "fallback_breakdown": fallback["breakdown"],
        "hash_diverge_count": diverge["diverge_count"],
        "hash_diverge_rate": round(diverge["diverge_rate"], 3),
        "diverge_breakdown": diverge["breakdown"],
        "tool_usage": tool_usage,
        "decision_latency": latency,
    }


def generate_markdown_summary(summary: dict[str, Any]) -> str:
    """Generate human-readable markdown summary."""
    lines = [
        f"# Reasoner Multi-Game Baseline — {summary['run_date']}",
        "",
        "**Run metadata:**",
        f"- Commit: `{summary['git_sha']}`",
        f"- Model: `{summary['model']}`",
        f"- Games: {summary['games_completed']} (average {summary['average_turns_per_game']} turns/game)",
        f"- Eligible Reasoner turns: {summary['eligible_reasoner_turns']}",
        "",
        f"**Commit Rate:** {summary['commit_rate']:.1%} ({summary['commit_count']} / {summary['eligible_reasoner_turns']})",
    ]
    
    if summary.get("line_source_breakdown"):
        lines.append("")
        lines.append("Line sources:")
        for source, count in summary["line_source_breakdown"].items():
            pct = count / summary["commit_count"] * 100 if summary["commit_count"] > 0 else 0
            lines.append(f"- {source}: {count} ({pct:.1f}%)")
    
    lines.extend([
        "",
        f"**Fallback Rate:** {summary['fallback_rate']:.1%} ({summary['fallback_count']} / {summary['eligible_reasoner_turns']})",
    ])
    
    if summary.get("fallback_breakdown"):
        for reason, count in summary["fallback_breakdown"].items():
            lines.append(f"- {reason}: {count}")
    
    lines.extend([
        "",
        f"**Hash Diverge Rate:** {summary['hash_diverge_rate']:.1%} ({summary['hash_diverge_count']} / {summary.get('hash_diverge_rate_denominator', 'N/A')})",
    ])
    
    if summary.get("diverge_breakdown"):
        for dtype, count in summary["diverge_breakdown"].items():
            lines.append(f"- {dtype}: {count}")
    
    if summary.get("exemptions"):
        lines.append("")
        lines.append(f"**Exemptions:** {sum(summary['exemptions'].values())} turns")
        for reason, count in summary["exemptions"].items():
            lines.append(f"- {reason}: {count}")
    
    tool_usage = summary.get("tool_usage", {})
    if tool_usage.get("tool_breakdown"):
        lines.extend([
            "",
            "**Tool usage:**",
            f"- Total tool calls: {tool_usage['total_tool_calls']}",
            f"- Total model calls: {tool_usage['total_model_calls']}",
        ])
        for tool, count in tool_usage["tool_breakdown"].items():
            lines.append(f"- {tool}: {count}")
    
    latency = summary.get("decision_latency", {})
    if latency.get("count", 0) > 0:
        lines.extend([
            "",
            "**Decision latency:**",
            f"- Median: {latency['median_ms']}ms",
            f"- p95: {latency['p95_ms']}ms",
        ])
    
    lines.extend([
        "",
        "**Review notes:** See `review_notes.md`.",
    ])
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Generate Reasoner multi-game baseline report"
    )
    parser.add_argument(
        "--db",
        required=True,
        help="Path to SQLite database (e.g. ai_agent/reasoner_baseline.db)",
    )
    parser.add_argument(
        "--log",
        help="Path to agent_search.log (optional, for hash divergence parsing)",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output path for baseline_summary.json",
    )
    parser.add_argument(
        "--markdown",
        help="Output path for summary.md (optional)",
    )
    parser.add_argument(
        "--git-sha",
        help="Git commit SHA for this run",
    )
    parser.add_argument(
        "--model",
        help="Model identifier (e.g. gpt-4o)",
    )
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    
    logger.info("Generating baseline summary from %s", args.db)
    
    summary = generate_baseline_summary(
        db_path=args.db,
        log_path=args.log,
        git_sha=args.git_sha,
        model=args.model,
    )
    
    # Write JSON summary
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    logger.info("Wrote baseline_summary.json to %s", out_path)
    
    # Write markdown summary if requested
    if args.markdown:
        md_content = generate_markdown_summary(summary)
        md_path = Path(args.markdown)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        with open(md_path, "w") as f:
            f.write(md_content)
        logger.info("Wrote summary.md to %s", md_path)
    
    # Print brief summary to console
    print("\n" + "=" * 60)
    print(f"Reasoner Baseline — {summary['run_date']}")
    print("=" * 60)
    print(f"Games: {summary['games_completed']}")
    print(f"Eligible turns: {summary['eligible_reasoner_turns']}")
    print(f"Commit rate: {summary['commit_rate']:.1%}")
    print(f"Fallback rate: {summary['fallback_rate']:.1%}")
    print(f"Hash diverge rate: {summary['hash_diverge_rate']:.1%}")
    print("=" * 60)


if __name__ == "__main__":
    main()
