"""
Riftbound AI Agent — Skill Implementations

Skills are the agent's only means of getting more information.  They divide
into read skills (pull state, never mutate) and helper skills (compute, never
mutate).  Action skills are not called here — they are realised as the agent's
final move and validated by Godot.

All functions in this module are pure with respect to game state.  They operate
on a snapshot that was pushed by Godot at the start of each decision request.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

# Paths to card data relative to workspace root (resolved at import time)
_WORKSPACE = Path(__file__).resolve().parent.parent
_CARDS_DIR = _WORKSPACE / "Data" / "Cards"
_RULES_FILE = _WORKSPACE / "Docs" / "Game Rules" / "riftbound-implementation-rules.md"

# In-memory caches populated lazily
_card_cache: dict[str, dict] = {}
_rules_text: str = ""

# State injected by main.py on each AI trigger
_current_brief_state: dict = {}
_current_full_state_text: str = ""
_current_legal_moves: list[str] = []

# History context injected by agent.py on each decision (for get_opponent_history)
_current_memory: Any = None
_current_game_id: str = ""

# Scout-search context injected by agent.build_goal_overlay before the strategist
# runs (Phase 1). A pre-summarized list of the engine's top candidate lines for
# THIS turn, so the strategist's search_turn tool can ground its goals in what the
# search actually finds rather than a static snapshot. Empty when no scout ran.
_current_scout_lines: list[dict] = []
_current_scout_stats: dict = {}


# ── State injection (called by main.py) ──────────────────────────────────────


def set_state(brief_state: dict) -> None:
    """Called once per decision request to install the latest Godot state."""
    global _current_brief_state, _current_full_state_text, _current_legal_moves
    _current_brief_state = brief_state
    _current_full_state_text = brief_state.get("full_state_text", "")
    _current_legal_moves = brief_state.get("legal_moves", [])


def set_history_context(memory: Any, game_id: str) -> None:
    """Called once per decision request so get_opponent_history can read real history."""
    global _current_memory, _current_game_id
    _current_memory = memory
    _current_game_id = game_id


def set_search_context(scout_lines: list[dict] | None, search_stats: dict | None = None) -> None:
    """Install the scout-search summaries the strategist's search_turn tool serves.

    Called by agent.build_goal_overlay before running the strategist. Pass an
    already-summarized, compact line list (see agent._summarize_lines_for_strategist)
    so this module stays a dumb accessor. Clearing (None) resets it so a later turn
    without a scout search does not serve stale lines.
    """
    global _current_scout_lines, _current_scout_stats
    _current_scout_lines = scout_lines or []
    _current_scout_stats = search_stats or {}


# ── Read Skills ───────────────────────────────────────────────────────────────


def get_full_state() -> str:
    """Return the full board description for this seat as text."""
    return _current_full_state_text or json.dumps(_current_brief_state, indent=2)


def get_zone(zone_id: str) -> str:
    """
    Return a focused description of one zone.
    zone_id examples: "my_hand", "my_base_units", "battlefield-a",
                      "opponent_base_units", "my_runes"
    """
    bs = _current_brief_state
    if not bs:
        return "No state available."

    if zone_id == "my_hand":
        return _format_hand(bs.get("my_hand", []))
    if zone_id == "my_base_units":
        return _format_units(bs.get("my_base_units", []))
    if zone_id == "opponent_base_units":
        return _format_units(bs.get("opponent_base_units", []))
    if zone_id == "my_runes":
        return _format_runes(bs.get("my_runes", []))
    if zone_id.startswith("battlefield-"):
        for bf in bs.get("battlefields", []):
            if bf["battlefield_id"] == zone_id:
                return _format_battlefield(bf)
        return f"Battlefield '{zone_id}' not found."

    return f"Unknown zone '{zone_id}'."


def get_card_detail(card_id: str) -> str:
    """Return the full definition text of a card by its instance_id or definition_id."""
    # Strip numeric suffix to get definition id: "noxus-hopeful-2" → "noxus-hopeful"
    def_id = re.sub(r"-\d+$", "", card_id)
    card = _find_card_definition(def_id)
    if card is None:
        return f"Card '{card_id}' not found in card database."
    summary = {
        "id": card.get("id"),
        "name": card.get("name"),
        "card_type": card.get("card_type"),
        "energy_cost": card.get("energy_cost"),
        "power_cost": card.get("power_cost"),
        "might": card.get("might"),
        "keywords": card.get("keywords"),
        "effect_text": card.get("effect_text", ""),
        "flavor_text": card.get("flavor_text", ""),
        "abilities": card.get("abilities", []),
    }
    return json.dumps(summary, indent=2)


def get_opponent_history() -> str:
    """
    Return a description of what the opponent has done this game: current
    public snapshot plus the tracked log of visible opponent actions.
    """
    bs = _current_brief_state
    lines = [
        "Opponent public info:",
        f"  Score: {bs.get('opponent_score', '?')}",
        f"  Hand size: {bs.get('opponent_hand_size', '?')}",
        f"  Base units: {_format_units(bs.get('opponent_base_units', []))}",
    ]
    recent = ""
    if _current_memory is not None and _current_game_id:
        recent = _current_memory.opponent_actions_text(_current_game_id)
    lines.append(recent or "  (No opponent actions recorded yet this game.)")
    return "\n".join(lines)


def lookup_rule(query: str) -> str:
    """Search the versioned implementation rules for the given topic or keyword."""
    text = _load_rules()
    if not text:
        return "Rules text not available."

    query_lower = query.lower()
    keywords = [w for w in re.split(r"\W+", query_lower) if len(w) >= 3]

    # Split rules into sections by ## heading
    sections = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    scored: list[tuple[int, str]] = []
    for section in sections:
        score = sum(section.lower().count(kw) for kw in keywords)
        if score > 0:
            scored.append((score, section))

    if not scored:
        return f"No rules passage found matching '{query}'."

    scored.sort(key=lambda x: x[0], reverse=True)
    top = "\n\n---\n\n".join(_trim_section(s) for _, s in scored[:2])
    return f"Rules excerpt (query: '{query}'):\n\n{top}"


# Maximum characters returned per matched rules section.  Keeps a lookup from
# negating the token savings of the layered system prompt.
_RULE_SECTION_CHAR_CAP = 1200


def _trim_section(section: str) -> str:
    """Trim a matched rules section to a bounded length on a line boundary."""
    section = section.strip()
    if len(section) <= _RULE_SECTION_CHAR_CAP:
        return section
    clipped = section[:_RULE_SECTION_CHAR_CAP]
    # Cut back to the last full line so we never end mid-sentence.
    nl = clipped.rfind("\n")
    if nl > 0:
        clipped = clipped[:nl]
    return clipped.rstrip() + "\n… (truncated — call lookup_rule with a narrower query for more)"


def get_keyword(name: str) -> str:
    """Return the precise glossary entry for a single keyword, if known."""
    from .system_prompt import KEYWORD_GLOSSARY

    key = (name or "").strip().lower()
    if key in KEYWORD_GLOSSARY:
        return KEYWORD_GLOSSARY[key]
    # Fall back to a fuzzy match on the rules text for unknown keywords.
    available = ", ".join(sorted(KEYWORD_GLOSSARY))
    return (
        f"No glossary entry for '{name}'. Known keywords: {available}. "
        f"Try lookup_rule('{name}') for a rules passage."
    )


# ── Helper Skills ─────────────────────────────────────────────────────────────


def list_legal_moves() -> list[str]:
    """Return the current enumerated legal moves (populated per-trigger from Godot)."""
    return _current_legal_moves


def simulate_move(move: dict) -> dict:
    """
    Return the engine-truth result of playing this move, as structured facts.

    Phase 2.5: outcomes are computed by Godot's rules engine on a clone of the
    live state (not guessed). Godot pre-simulates each legal move and inlines the
    result into the brief state keyed by the command string; this skill looks up
    that SimResult. The returned dict separates the deterministic
    `resolved_if_unanswered` line (facts the agent may assert) from a
    `response_window` flag (a hidden opponent choice the agent must hedge).
    """
    bs = _current_brief_state
    command = _move_to_command(move)
    sims = bs.get("move_simulations", {}) or {}

    if command in sims:
        return sims[command]

    # Not pre-simulated. Tell the model plainly rather than inventing an outcome.
    legal = command in (bs.get("legal_moves", []) or [])
    return {
        "legal": legal,
        "error": (
            f"No engine simulation available for '{command}'. "
            "Do not assert its outcome as fact — reason from the labeled "
            "legal_moves and mark the result uncertain."
        ),
    }


def simulate_line(moves: list) -> dict:
    """
    Return the engine-truth result of a scripted multi-step line of YOUR OWN
    moves (e.g. move a unit into combat, then play a trick to win it).

    Phase 2.5: Godot pre-simulates auto-detected combat lines (a contested move
    followed by an affordable Action/Reaction). This looks up the matching
    LineResult. `resolved_if_unanswered` is the deterministic outcome assuming the
    opponent does not respond; each entry in `opponent_windows` is a point where
    the opponent could have answered (hedge those).
    """
    bs = _current_brief_state
    commands = [_move_to_command(m) for m in (moves or [])]
    key = " ; ".join(commands)
    line_sims = bs.get("line_simulations", {}) or {}

    if key in line_sims:
        return line_sims[key]

    # Fall back to chaining single-move sims where possible so the agent still
    # gets the first move's verified outcome rather than nothing.
    move_sims = bs.get("move_simulations", {}) or {}
    first = commands[0] if commands else ""
    if first in move_sims:
        return {
            "legal": move_sims[first].get("legal", False),
            "applied_moves": [first],
            "stopped_reason": "line_not_presimulated",
            "resolved_if_unanswered": move_sims[first].get("resolved_if_unanswered"),
            "error": (
                "Only the first move of this line was simulated by the engine. "
                "Treat later steps as uncertain and hedge."
            ),
        }
    return {
        "legal": False,
        "applied_moves": [],
        "stopped_reason": "not_simulated",
        "error": (
            f"No engine simulation available for the line '{key}'. "
            "Do not assert its outcome as fact."
        ),
    }


def _move_to_command(move: dict) -> str:
    """Build the same console command string Godot keys pre-simulations by.

    Reuses the Move.to_command() translation so the lookup key matches exactly.
    Accepts either a raw {action, parameters} dict or an already-built string.
    """
    if isinstance(move, str):
        return move
    try:
        from .schemas import Move

        return Move(**move).to_command()
    except Exception:
        # Best-effort fallback for malformed tool input.
        action = (move or {}).get("action", "")
        return str(action)


def search_turn(top_n: int = 5) -> dict[str, Any]:
    """
    Return the engine's top candidate lines for THIS turn (scout search).

    Phase 1 (search-grounded strategist): before the strategist runs, the engine
    may run a cheap base-profile search and inline its best full-turn lines. This
    tool surfaces them as ENGINE-TRUTH facts — each line is a sequence the rules
    engine actually simulated, with its mechanical score and the top score terms
    driving it. Use it to set goals grounded in what the search can achieve:
    - pick goals that PUSH the search toward a strong line it already found, or
    - REDIRECT it when every top line ignores a winning idea you can see.
    If no scout search ran, 'lines' is empty — fall back to evaluate_position.
    """
    if not _current_scout_lines:
        return {
            "lines": [],
            "note": (
                "No scout search available this turn. Ground goals with "
                "evaluate_position and the board summary instead."
            ),
        }
    return {
        "lines": _current_scout_lines[: max(1, int(top_n or 5))],
        "search_stats": _current_scout_stats,
        "note": (
            "Scores are mechanical (base profile). A high-scoring line is the "
            "search's current best guess; set goals to sharpen or redirect it."
        ),
    }


def evaluate_position() -> dict[str, Any]:
    """
    Return a heuristic assessment of the current position.
    Higher score_advantage means better for the AI seat.
    """
    bs = _current_brief_state
    if not bs:
        return {"error": "No state available."}

    my_score = bs.get("my_score", 0)
    opp_score = bs.get("opponent_score", 0)
    victory_score = 8

    # Count units on board and battlefields controlled
    my_units_on_board = len(bs.get("my_base_units", []))
    opp_units_on_board = len(bs.get("opponent_base_units", []))
    my_bfs = 0
    opp_bfs = 0
    my_pi = bs.get("my_player_index", 0)
    for bf in bs.get("battlefields", []):
        my_units_on_board += len(bf.get("my_units", []))
        opp_units_on_board += len(bf.get("opponent_units", []))
        ctrl = bf.get("controller_index", -1)
        if ctrl == my_pi:
            my_bfs += 1
        elif ctrl == (1 - my_pi):
            opp_bfs += 1

    score_advantage = my_score - opp_score
    unit_advantage = my_units_on_board - opp_units_on_board
    bf_advantage = my_bfs - opp_bfs

    assessment = "losing" if score_advantage < -2 else (
        "ahead" if score_advantage > 2 else "even"
    )
    points_to_win = victory_score - my_score
    opp_points_to_win = victory_score - opp_score

    # Resource assessment: total playable energy = pool + untapped runes
    runes = bs.get("my_runes", [])
    untapped = [r for r in runes if not r.get("is_exhausted", False)]
    total_energy = bs.get("my_energy", 0) + len(untapped)
    domain_power: dict[str, int] = dict(bs.get("my_power", {}) or {})
    for r in untapped:
        d = r.get("domain", "")
        domain_power[d] = domain_power.get(d, 0) + 1
    playable_cards = sum(
        1 for c in bs.get("my_hand", [])
        if c.get("energy_cost", 0) <= total_energy
        and all(
            domain_power.get(pc["domain"], 0) >= pc["amount"]
            for pc in (c.get("power_cost") or [])
        )
    )

    return {
        "score_advantage": score_advantage,
        "my_score": my_score,
        "opponent_score": opp_score,
        "points_to_win": points_to_win,
        "opponent_points_to_win": opp_points_to_win,
        "unit_advantage": unit_advantage,
        "my_units_on_board": my_units_on_board,
        "opponent_units_on_board": opp_units_on_board,
        "battlefields_controlled": my_bfs,
        "opponent_battlefields_controlled": opp_bfs,
        "bf_advantage": bf_advantage,
        "hand_size": len(bs.get("my_hand", [])),
        "total_playable_energy": total_energy,
        "domain_power_available": domain_power,
        "playable_cards_in_hand": playable_cards,
        "assessment": assessment,
    }


# ── Formatting helpers ────────────────────────────────────────────────────────


def format_effect_text(text: str) -> str:
    """Render multi-line effect_text as one effect string."""
    return " ".join(line.strip() for line in text.splitlines() if line.strip())


def _format_hand(hand: list[dict]) -> str:
    if not hand:
        return "(empty hand)"
    lines = []
    for c in hand:
        cost = f"{c.get('energy_cost', 0)}E"
        if c.get("power_cost"):
            cost += " + " + _power_cost_str(c["power_cost"])
        kw = ", ".join(c.get("keywords", []))
        might = f" Might:{c['might']}" if c.get("might") is not None else ""
        lines.append(f"  {c['instance_id']} — {c['name']} [{c['card_type']}] ({cost}){might} {kw}")
        effect = c.get("effect_text", "")
        if effect:
            lines.append(f"    Effect: {format_effect_text(effect)}")
    return "\n".join(lines)


def _format_units(units: list[dict]) -> str:
    if not units:
        return "(none)"
    parts = []
    for u in units:
        status = []
        if u.get("is_attacker"):
            status.append("ATK")
        if u.get("is_defender"):
            status.append("DEF")
        if u.get("is_exhausted"):
            status.append("EXH")
        if u.get("is_stunned"):
            status.append("STUN")
        if u.get("damage", 0) > 0:
            status.append(f"DMG:{u['damage']}")
        st = " ".join(status) or "ready"
        parts.append(
            f"  {u['instance_id']} — {u['name']} "
            f"({u['current_might']}/{u['base_might']} Might) @ {u['location']} [{st}]"
        )
        effect = u.get("effect_text", "")
        if effect:
            parts.append(f"    Effect: {format_effect_text(effect)}")
    return "\n".join(parts)


def _format_runes(runes: list[dict]) -> str:
    if not runes:
        return "(no runes)"
    return ", ".join(
        f"rune-{r['rune_index']}({r['domain']}{'*' if r['is_exhausted'] else ''})"
        for r in runes
    )


def _format_battlefield(bf: dict) -> str:
    ctrl = bf.get("controller_index", -1)
    ctrl_str = "uncontrolled" if ctrl == -1 else f"P{ctrl + 1}"
    contested = " CONTESTED" if bf.get("is_contested") else ""
    lines = [f"[{bf['battlefield_id']}] {bf['display_name']} — {ctrl_str}{contested}"]
    bf_effect = bf.get("effect_text", "")
    if bf_effect:
        lines.append(f"  Effect: {format_effect_text(bf_effect)}")
    if bf.get("my_units"):
        lines.append("  My units: " + _format_units(bf["my_units"]))
    if bf.get("opponent_units"):
        lines.append("  Opponent units: " + _format_units(bf["opponent_units"]))
    if bf.get("has_facedown"):
        lines.append("  [hidden card present]")
    return "\n".join(lines)


def _power_cost_str(power_cost: list[dict]) -> str:
    if not power_cost:
        return ""
    return " ".join(f"{pc.get('amount', 1)}{pc.get('domain', '?').upper()[:3]}" for pc in power_cost)


# ── Card / state lookup helpers ───────────────────────────────────────────────


def _find_card_definition(def_id: str) -> Optional[dict]:
    if not _card_cache:
        _load_card_cache()
    return _card_cache.get(def_id)


def _load_card_cache() -> None:
    global _card_cache
    for json_file in _CARDS_DIR.glob("*.json"):
        try:
            cards = json.loads(json_file.read_text(encoding="utf-8"))
            if isinstance(cards, list):
                for card in cards:
                    if "id" in card:
                        _card_cache[card["id"]] = card
            elif isinstance(cards, dict) and "id" in cards:
                _card_cache[cards["id"]] = cards
        except Exception:
            pass  # silently skip malformed files


def _load_rules() -> str:
    global _rules_text
    if not _rules_text and _RULES_FILE.exists():
        _rules_text = _RULES_FILE.read_text(encoding="utf-8")
    return _rules_text
