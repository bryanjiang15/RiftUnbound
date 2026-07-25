"""ANSI-colored, compact formatters for agent_search.log."""
from __future__ import annotations

from typing import Any, Mapping

# ESC sequences — render in a terminal (`less -R`, `cat`) or an ANSI Colors
# editor extension. Plain text editors show the escapes as noise.
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"


def paint(text: str, *codes: str) -> str:
    if not codes:
        return text
    return f"{''.join(codes)}{text}{RESET}"


def _is_zeroish(value: Any) -> bool:
    if value is None or value is False:
        return True
    if isinstance(value, bool):
        return False  # True is meaningful
    if isinstance(value, (int, float)):
        return abs(float(value)) < 1e-9
    if isinstance(value, str):
        return value.strip() == ""
    return False


def nonzero_items(data: Mapping[str, Any] | None) -> list[tuple[str, Any]]:
    if not data:
        return []
    return [(k, v) for k, v in data.items() if not _is_zeroish(v)]


def _fmt_num(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.3g}"


def _signed_num(value: float) -> str:
    body = _fmt_num(abs(value))
    if value > 0:
        return paint(f"+{body}", GREEN)
    if value < 0:
        return paint(f"-{body}", RED)
    return paint("0", DIM)


def format_stats_line(stats: Mapping[str, Any] | None) -> str:
    """One-line search stats, e.g. mode=main nodes=4 … 19ms exhausted."""
    if not stats:
        return paint("Stats:", DIM) + " " + paint("—", DIM)
    mode = stats.get("mode", "?")
    parts = [
        f"mode={paint(str(mode), CYAN)}",
        f"nodes={stats.get('nodes_explored', '?')}",
        f"branches={stats.get('branches_expanded', '?')}",
        f"tt={stats.get('transposition_hits', '?')}",
        f"depth={stats.get('max_depth_reached', '?')}",
        f"beam={stats.get('beam_width', '?')}",
    ]
    ms = stats.get("elapsed_ms")
    if ms is not None:
        parts.append(paint(f"{ms}ms", YELLOW))
    reason = stats.get("stopped_reason")
    if reason:
        parts.append(paint(str(reason), MAGENTA))
    return paint("Stats:", DIM) + " " + " ".join(str(p) for p in parts)


def format_breakdown_line(breakdown: Mapping[str, Any] | None) -> str:
    """Non-zero score terms on one line, total at the end."""
    if not breakdown:
        return paint("Breakdown:", DIM) + " " + paint("—", DIM)
    # Contextual fields that are not score contributions.
    meta_keys = {"points_to_win", "shaping_clamped"}
    total = breakdown.get("total")
    parts: list[str] = []
    for key, value in nonzero_items(breakdown):
        if key == "total":
            continue
        if key in meta_keys:
            if isinstance(value, bool):
                parts.append(f"{key}={paint(str(value).lower(), YELLOW)}")
            elif isinstance(value, (int, float)):
                parts.append(f"{key}={paint(_fmt_num(float(value)), CYAN)}")
            else:
                parts.append(f"{key}={value}")
        elif isinstance(value, bool):
            parts.append(f"{key}={paint(str(value).lower(), YELLOW)}")
        elif isinstance(value, (int, float)):
            parts.append(f"{key}{_signed_num(float(value))}")
        else:
            parts.append(f"{key}={value}")
    body = " ".join(parts) if parts else paint("(all zero)", DIM)
    if total is not None and isinstance(total, (int, float)):
        body = f"{body} → {paint('total=', DIM)}{_signed_num(float(total))}"
    return paint("Breakdown:", DIM) + " " + body


def format_delta_line(delta: Mapping[str, Any] | None) -> str:
    """Non-zero / meaningful resolved-state fields on one line."""
    if not delta:
        return paint("Delta:", DIM) + " " + paint("—", DIM)
    # Prefer a stable, readable order; then any leftover nonzero keys.
    preferred = (
        "next_decision",
        "my_score_after",
        "opp_score_after",
        "conquer",
        "wins_game",
    )
    parts: list[str] = []
    seen: set[str] = set()

    def _append(key: str, value: Any) -> None:
        if key in seen or _is_zeroish(value):
            return
        seen.add(key)
        if key in ("my_score_after", "opp_score_after") and isinstance(value, (int, float)):
            parts.append(f"{key}={paint(_fmt_num(float(value)), CYAN)}")
        elif key in ("conquer", "wins_game") and value is True:
            parts.append(f"{paint(key, GREEN)}={paint('true', BOLD + GREEN)}")
        elif isinstance(value, bool):
            parts.append(f"{key}={paint(str(value).lower(), YELLOW)}")
        elif isinstance(value, (int, float)):
            parts.append(f"{key}={_fmt_num(float(value))}")
        else:
            parts.append(f"{key}={paint(str(value), WHITE)}")

    for key in preferred:
        if key not in delta:
            continue
        if key == "next_decision" and delta[key] not in (None, ""):
            parts.append(f"next={paint(str(delta[key]), YELLOW)}")
            seen.add(key)
        else:
            _append(key, delta[key])
    for key, value in delta.items():
        _append(key, value)

    body = " ".join(parts) if parts else paint("(empty)", DIM)
    return paint("Delta:", DIM) + " " + body


def format_line_header(line_id: str, score: float) -> str:
    colored_score = paint(
        f"{score:+.3f}",
        GREEN if score > 0 else RED if score < 0 else DIM,
    )
    return f"{paint(line_id, BOLD + CYAN)} | score={colored_score}"


def format_banner(title: str) -> list[str]:
    bar = paint("═" * 72, DIM)
    return ["", bar, paint(title, BOLD + CYAN), bar]


def format_thin_banner(title: str) -> list[str]:
    bar = paint("─" * 72, DIM)
    return ["", bar, paint(title, BOLD + CYAN), bar]
