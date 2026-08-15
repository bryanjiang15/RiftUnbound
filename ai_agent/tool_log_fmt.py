"""ANSI formatters for Claude/Cursor-style tool-call logging."""
from __future__ import annotations

import json
from typing import Any

from .search_log_fmt import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    MAGENTA,
    RED,
    YELLOW,
    format_candidate_corpus,
    paint,
)

# Soft cap for argument / result lines in the log (full payload still goes to the model).
_ARG_VALUE_MAX = 120
_RESULT_MAX = 280


def _short(value: Any, limit: int = _ARG_VALUE_MAX) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, default=str, separators=(",", ":"))
        except TypeError:
            text = str(value)
    text = text.replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def summarize_tool_result(name: str, result: Any) -> str:
    """One-line human summary of a tool result (Claude ⎿ style)."""
    if isinstance(result, str):
        return _short(result, _RESULT_MAX)

    if not isinstance(result, dict):
        return _short(result, _RESULT_MAX)

    if name in ("commit_line", "emit_goals"):
        if result.get("accepted"):
            return f"accepted terminal={name}"
        return f"rejected error={_short(result.get('error', 'invalid terminal'), 180)}"

    if name == "search_for":
        matches = result.get("matches") or []
        parts = [
            f"matches={len(matches)}",
            f"corpus={result.get('corpus_size', '?')}",
        ]
        if result.get("source"):
            parts.append(f"source={result['source']}")
        if matches:
            top = matches[0]
            parts.append(f"top={top.get('line_id', '?')}")
            sat = top.get("satisfaction")
            if sat is not None:
                parts.append(f"sat={sat:.2f}" if isinstance(sat, float) else f"sat={sat}")
        if result.get("note"):
            parts.append(_short(result["note"], 80))
        return " ".join(str(p) for p in parts)

    if name in ("simulate_move", "simulate_line"):
        parts = [f"legal={result.get('legal')}"]
        if result.get("source"):
            parts.append(f"source={result['source']}")
        if result.get("stopped_reason"):
            parts.append(f"stopped={result['stopped_reason']}")
        if result.get("error"):
            parts.append(f"error={_short(result['error'], 100)}")
        elif result.get("resolved_if_unanswered") is not None:
            parts.append("resolved✓")
        if result.get("opponent_windows") or result.get("response_window"):
            parts.append("opp_window")
        return " ".join(str(p) for p in parts)

    if name == "deepen":
        lines = result.get("candidate_lines") or []
        parts = [f"lines={len(lines)}", f"legal={result.get('legal', True)}"]
        if result.get("source"):
            parts.append(f"source={result['source']}")
        if result.get("seed_moves"):
            parts.append(f"seed={_short(result['seed_moves'], 80)}")
        if result.get("error"):
            parts.append(f"error={_short(result['error'], 100)}")
        return " ".join(str(p) for p in parts)

    if name == "search_turn":
        lines = result.get("lines") or []
        parts = [f"lines={len(lines)}"]
        if lines:
            parts.append(f"top={lines[0].get('line_id', '?')}")
        if result.get("note"):
            parts.append(_short(result["note"], 80))
        return " ".join(str(p) for p in parts)

    if name == "evaluate_position":
        if result.get("error"):
            return f"error={_short(result['error'], 120)}"
        keys = (
            "assessment",
            "score_advantage",
            "my_score",
            "opponent_score",
            "unit_advantage",
            "bf_advantage",
        )
        bits = [f"{k}={result[k]}" for k in keys if k in result]
        return " ".join(bits) if bits else _short(result, _RESULT_MAX)

    if name == "list_legal_moves":
        if isinstance(result, list):
            return f"count={len(result)} " + _short(result[:5], 160)
        return _short(result, _RESULT_MAX)

    if name == "get_card_detail":
        if isinstance(result, dict):
            label = result.get("name") or result.get("id") or result.get("card_id")
            if label:
                return str(label)
        return _short(result, _RESULT_MAX)

    if result.get("error"):
        return f"error={_short(result['error'], 160)}"
    return _short(result, _RESULT_MAX)


def format_tool_call_lines(entry: dict[str, Any]) -> list[str]:
    """Claude/Cursor-style block for one tool invocation."""
    name = str(entry.get("name", "?"))
    args = entry.get("args") or {}
    summary = entry.get("summary") or entry.get("result_summary") or ""
    round_i = entry.get("round")

    header = f"{paint('●', BOLD + CYAN)} {paint(name, BOLD + CYAN)}"
    if round_i is not None:
        header = f"{header}  {paint(f'round {round_i}', DIM)}"
    lines = [header]

    if isinstance(args, dict) and args:
        for key, value in args.items():
            lines.append(
                f"  {paint(str(key) + ':', DIM)} {_short(value)}"
            )
    elif args:
        lines.append(f"  {paint('args:', DIM)} {_short(args)}")

    if summary:
        lines.append(f"  {paint('⎿', DIM + GREEN)} {summary}")
    return lines


def format_tools_session(
    *,
    stage: str,
    turn: Any,
    decision_type: Any,
    state: Any,
    game_id: str,
    ts: str,
    tool_trace: list[dict[str, Any]],
    outcome: str,
    reasoning: str = "",
    final_output: Any = None,
    scout_lines: list[Any] | None = None,
    scout_stats: dict[str, Any] | None = None,
) -> list[str]:
    """Full tool-call block embedded in agent_search.log."""
    title = (
        f"{paint(stage, BOLD + MAGENTA)}  "
        f"Turn {turn}  "
        f"{paint(str(decision_type), CYAN)}  "
        f"{paint(str(state), DIM)}  "
        f"Game: {game_id}  [{ts}]"
    )
    bar = paint("─" * 72, DIM)
    lines = ["", bar, title, bar]

    if scout_lines:
        heading = f"Scout lines ({len(scout_lines)}):"
        lines.extend(
            format_candidate_corpus(
                scout_lines,
                stats=scout_stats,
                heading=heading,
            )
        )
        lines.append("")

    if not tool_trace:
        lines.append(paint("  (no tools — model answered directly)", DIM))
    else:
        lines.append(
            paint(f"Tool calls ({len(tool_trace)}):", BOLD)
        )
        for i, entry in enumerate(tool_trace):
            if i:
                lines.append("")
            lines.extend(format_tool_call_lines(entry))

    if reasoning.strip():
        lines.append("")
        lines.append(paint("Reasoner recommendation:", BOLD + MAGENTA))
        lines.extend(f"  {line}" for line in reasoning.strip().splitlines())

    if final_output is not None:
        lines.append("")
        lines.append(paint("Final output:", BOLD + MAGENTA))
        if isinstance(final_output, dict):
            rendered = json.dumps(final_output, indent=2, default=str)
        else:
            rendered = str(final_output)
        lines.extend(f"  {line}" for line in rendered.splitlines())

    # Outcome coloring: errors/pass soft-fail vs success.
    out_lower = outcome.lower()
    if "empty" in out_lower or "fail" in out_lower or "error" in out_lower:
        out_paint = RED
    elif out_lower.startswith("pass"):
        out_paint = YELLOW
    else:
        out_paint = GREEN
    lines.append("")
    lines.append(f"{paint('→', BOLD)} {paint(outcome, out_paint)}")
    lines.append("")
    return lines
