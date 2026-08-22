"""ANSI-colored, compact formatters for agent_search.log."""
from __future__ import annotations

import json
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


def _fmt_pct(value: float) -> str:
    pct = max(0.0, min(1.0, float(value))) * 100.0
    if abs(pct - round(pct)) < 1e-9:
        return f"{int(round(pct))}%"
    return f"{pct:.1f}%"


def format_risk_line(risk: Mapping[str, Any] | None) -> str:
    """One-line reaction-risk summary (worst/expected + flags)."""
    label = paint("Risk:", BOLD + YELLOW)
    if not risk:
        return label + " " + paint("—", DIM)
    parts: list[str] = []
    threats = list(risk.get("threats") or [])
    skipped = [
        s for s in (risk.get("skipped") or [])
        if isinstance(s, Mapping)
    ]
    worst = risk.get("risk_worst")
    expected = risk.get("risk_expected")
    if threats and isinstance(worst, (int, float)) and not _is_zeroish(worst):
        parts.append(f"worst={_signed_num(float(worst))}")
    elif threats and isinstance(worst, (int, float)):
        parts.append(f"worst={paint('0', DIM)}")
    if isinstance(expected, (int, float)) and not _is_zeroish(expected):
        parts.append(f"expected={_signed_num(float(expected))}")
    if risk.get("needs_recapture") is True:
        parts.append(paint("plan_broken", BOLD + RED))
    if risk.get("can_recapture") is True:
        parts.append(paint("can_recapture", GREEN))
    if not threats and skipped:
        parts.append(paint("no legal assumed interrupt", YELLOW))
    elif not threats:
        parts.append(paint("clear", GREEN))
    info_mode = str(risk.get("information_mode") or "").strip()
    if info_mode and threats:
        parts.append(paint(info_mode, DIM))
    if threats:
        parts.append(paint(f"({len(threats)} probed)", DIM))
    if skipped:
        skip_bits = []
        for item in skipped[:6]:
            card = str(item.get("card_id") or "?")
            reason = str(item.get("reason") or "skipped")
            skip_bits.append(f"{card}/{reason}")
        extra = "" if len(skipped) <= 6 else f" +{len(skipped) - 6}"
        parts.append(paint(f"skipped[{', '.join(skip_bits)}{extra}]", DIM))
    body = " ".join(str(p) for p in parts) if parts else paint("clear", GREEN)
    return label + " " + body


def format_risk_threat(threat: Mapping[str, Any]) -> str:
    """One probed assumed-interrupt threat."""
    card = str(threat.get("card_id") or threat.get("assumed_card") or "?")
    parts: list[str] = [paint(card, BOLD + WHITE)]
    p = threat.get("p_in_hand")
    if isinstance(p, (int, float)):
        parts.append(f"p={paint(_fmt_pct(float(p)), CYAN)}")
    delta = threat.get("window_delta")
    if isinstance(delta, (int, float)):
        parts.append(f"Δ={_signed_num(float(delta))}")
    after_move = str(threat.get("window_after_move") or "").strip()
    if after_move:
        parts.append(f"@{paint(after_move, YELLOW)}")
    if threat.get("plan_broken") is True:
        parts.append(paint("plan_broken", BOLD + RED))
    elif threat.get("script_legal") is False:
        parts.append(paint("script_illegal", RED))
    broken = list(threat.get("broken_claims") or [])
    if broken:
        claims = ", ".join(str(c) for c in broken)
        parts.append(f"broken=[{paint(claims, MAGENTA)}]")
    if threat.get("can_recapture") is True:
        parts.append(paint("recapture_ok", GREEN))
    recapture = threat.get("score_after_recapture")
    if isinstance(recapture, (int, float)) and not _is_zeroish(recapture):
        parts.append(f"after_recapture={_signed_num(float(recapture))}")
    note = str(threat.get("note") or "").strip()
    if note:
        parts.append(paint(note, DIM))
    return "    · " + " ".join(str(p) for p in parts)


def format_risk_block(risk: Mapping[str, Any] | None) -> list[str]:
    """Summary line plus indented probed threats."""
    if not risk:
        return []
    out = ["  " + format_risk_line(risk)]
    threats = list(risk.get("threats") or [])
    ordered = sorted(
        (t for t in threats if isinstance(t, Mapping)),
        key=lambda t: float(t.get("window_delta", 0.0) or 0.0),
        reverse=True,
    )
    for threat in ordered:
        out.append(format_risk_threat(threat))
    return out


def summarize_risk_payload(risk: Mapping[str, Any] | None) -> dict[str, Any]:
    """Compact risk summary for Reasoner prompts and tool corpora."""
    if not isinstance(risk, Mapping) or not risk:
        return {}
    if "risk_worst" not in risk and "threats" not in risk:
        return {}
    out: dict[str, Any] = {}
    for key in ("risk_worst", "risk_expected"):
        val = risk.get(key)
        if isinstance(val, (int, float)):
            out[key] = round(float(val), 3)
    for key in ("can_recapture", "needs_recapture"):
        if risk.get(key) is True:
            out[key] = True
    info = str(risk.get("information_mode") or "").strip()
    if info:
        out["information_mode"] = info
    threats_out: list[dict[str, Any]] = []
    threats = sorted(
        (t for t in (risk.get("threats") or []) if isinstance(t, Mapping)),
        key=lambda t: float(t.get("window_delta", 0.0) or 0.0),
        reverse=True,
    )
    for threat in threats[:3]:
        card_id = str(threat.get("card_id") or threat.get("assumed_card") or "")
        if not card_id:
            continue
        entry: dict[str, Any] = {"card_id": card_id}
        p = threat.get("p_in_hand")
        if isinstance(p, (int, float)):
            entry["p_in_hand"] = round(float(p), 3)
        delta = threat.get("window_delta")
        if isinstance(delta, (int, float)):
            entry["window_delta"] = round(float(delta), 3)
        after_move = str(threat.get("window_after_move") or "").strip()
        if after_move:
            entry["window_after_move"] = after_move
        if threat.get("plan_broken") is True:
            entry["plan_broken"] = True
        elif threat.get("script_legal") is False:
            entry["script_legal"] = False
        broken = list(threat.get("broken_claims") or [])
        if broken:
            entry["broken_claims"] = [str(c) for c in broken]
        if threat.get("can_recapture") is True:
            entry["can_recapture"] = True
        recapture = threat.get("score_after_recapture")
        if isinstance(recapture, (int, float)):
            entry["score_after_recapture"] = round(float(recapture), 3)
        note = str(threat.get("note") or "").strip()
        if note:
            entry["note"] = note
        threats_out.append(entry)
    if threats_out:
        out["threats"] = threats_out
    skipped = [
        {
            "card_id": str(s.get("card_id") or ""),
            "reason": str(s.get("reason") or ""),
        }
        for s in (risk.get("skipped") or [])
        if isinstance(s, Mapping) and str(s.get("card_id") or "")
    ]
    if skipped:
        out["skipped"] = skipped[:6]
    return out


def format_line_header(
    line_id: str,
    score: float,
    cluster_key: str = "",
    cluster_size: int = 0,
    *,
    risk_worst: float | None = None,
) -> str:
    colored_score = paint(
        f"{score:+.3f}",
        GREEN if score > 0 else RED if score < 0 else DIM,
    )
    header = f"{paint(line_id, BOLD + CYAN)} | score={colored_score}"
    if risk_worst is not None and abs(float(risk_worst)) >= 1e-9:
        header += f" | risk_worst={_signed_num(float(risk_worst))}"
    if cluster_key and int(cluster_size or 0) > 1:
        header += (
            f" | cluster={paint(str(cluster_key), WHITE)}"
            f" {paint(f'×{int(cluster_size)}', DIM)}"
        )
    return header


def _line_mapping(line: Any) -> Mapping[str, Any]:
    if isinstance(line, Mapping):
        return line
    if hasattr(line, "model_dump"):
        return line.model_dump()
    return {}


def _move_command(move: Any) -> str:
    if hasattr(move, "to_command"):
        return str(move.to_command())
    return str(move)


def format_candidate_line(line: Any) -> list[str]:
    """One candidate: id/score, moves, breakdown, delta, risk, opponent windows."""
    data = _line_mapping(line)
    line_id = str(data.get("line_id") or "?")
    try:
        score = float(data.get("score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    risk = data.get("risk")
    risk_worst: float | None = None
    if isinstance(risk, Mapping):
        raw_worst = risk.get("risk_worst")
        if isinstance(raw_worst, (int, float)):
            risk_worst = float(raw_worst)
    out = [format_line_header(
        line_id,
        score,
        cluster_key=str(data.get("cluster_key") or ""),
        cluster_size=int(data.get("cluster_size") or 0),
        risk_worst=risk_worst,
    )]
    moves = list(data.get("moves") or [])
    contexts = list(data.get("move_contexts") or [])
    for i, move in enumerate(moves):
        cmd = _move_command(move)
        ctx = contexts[i] if i < len(contexts) else {}
        if not isinstance(ctx, Mapping):
            ctx = {}
        kind = ctx.get("kind", "scripted")
        context_text = ctx.get("context", "") or ""
        if kind == "intermediate":
            note = context_text or "auto-resolved decision"
            out.append(
                f"  - {cmd}    "
                f"{paint('← [intermediate]', DIM + YELLOW)} "
                f"{paint(note, DIM)}"
            )
        elif context_text:
            out.append(f"  - {cmd}    {paint(f'({context_text})', DIM)}")
        else:
            out.append(f"  - {cmd}")
    out.append("  " + format_breakdown_line(data.get("score_breakdown") or {}))
    out.append("  " + format_delta_line(data.get("resolved_state") or {}))
    windows = data.get("opponent_windows") or []
    if "risk" in data and isinstance(risk, Mapping):
        out.extend(format_risk_block(risk))
    elif windows:
        out.append(
            "  "
            + paint("Risk:", BOLD + YELLOW)
            + " "
            + paint("not probed", YELLOW)
        )
    if windows:
        dumped = [
            w.model_dump() if hasattr(w, "model_dump") else w for w in windows
        ]
        out.append(
            "  "
            + paint("Opp windows:", DIM)
            + " "
            + paint(json.dumps(dumped, default=str, separators=(",", ":")), DIM)
        )
    return out


def format_candidate_corpus(
    lines: list[Any] | None,
    *,
    stats: Mapping[str, Any] | None = None,
    heading: str | None = "Candidate lines:",
) -> list[str]:
    """Stats + heading + each candidate line. Used by search and Reasoner logs."""
    out: list[str] = []
    if stats:
        out.append(format_stats_line(stats))
    if heading:
        out.append(paint(heading, BOLD))
    for line in lines or []:
        out.append("")
        out.extend(format_candidate_line(line))
    return out


def format_banner(title: str) -> list[str]:
    bar = paint("═" * 72, DIM)
    return ["", bar, paint(title, BOLD + CYAN), bar]


def format_thin_banner(title: str) -> list[str]:
    bar = paint("─" * 72, DIM)
    return ["", bar, paint(title, BOLD + CYAN), bar]
