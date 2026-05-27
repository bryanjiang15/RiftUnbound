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


# ── State injection (called by main.py) ──────────────────────────────────────


def set_state(brief_state: dict) -> None:
    """Called once per decision request to install the latest Godot state."""
    global _current_brief_state, _current_full_state_text, _current_legal_moves
    _current_brief_state = brief_state
    _current_full_state_text = brief_state.get("full_state_text", "")
    _current_legal_moves = brief_state.get("legal_moves", [])


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
    return json.dumps(card, indent=2)


def get_opponent_history() -> str:
    """
    Return a description of what the opponent has done this game.
    This is derived from the brief state (no separate history tracking yet).
    """
    bs = _current_brief_state
    lines = [
        "Opponent public info:",
        f"  Score: {bs.get('opponent_score', '?')}",
        f"  Hand size: {bs.get('opponent_hand_size', '?')}",
        f"  Base units: {_format_units(bs.get('opponent_base_units', []))}",
        "  (Detailed opponent history not yet tracked.)",
    ]
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
    top = "\n\n---\n\n".join(s for _, s in scored[:2])
    return f"Rules excerpt (query: '{query}'):\n\n{top}"


# ── Helper Skills ─────────────────────────────────────────────────────────────


def list_legal_moves() -> list[str]:
    """Return the current enumerated legal moves (populated per-trigger from Godot)."""
    return _current_legal_moves


def simulate_move(move: dict) -> str:
    """
    Simulate what would happen if the agent played this move.
    This is a lightweight heuristic simulation based on brief state — it does
    not invoke Godot's rules engine and may not capture edge cases.
    """
    action = move.get("action", "")
    p = move.get("parameters", {})
    bs = _current_brief_state

    if action == "end_turn":
        return "Turn would end.  Opponent takes over.  Score unchanged this action."

    if action == "pass":
        return "Pass priority/focus.  No state change."

    if action == "play_card":
        card_id = p.get("card_id", "")
        card = _find_hand_card(bs, card_id)
        if not card:
            return f"Card '{card_id}' not found in hand."
        dest = p.get("destination", "base")
        return (
            f"Play {card.get('name', card_id)} ({card.get('card_type', '?')}) "
            f"to {dest}.  Costs {card.get('energy_cost', 0)} energy + "
            f"{_power_cost_str(card.get('power_cost', []))}.  "
            f"Card enters exhausted (unless Accelerate used)."
        )

    if action == "move_unit":
        unit_ids = p.get("unit_ids", [])
        dest = p.get("destination", "?")
        names = []
        for uid in unit_ids:
            u = _find_unit_anywhere(bs, uid)
            names.append(u.get("name", uid) if u else uid)
        enemy_at_dest = _enemy_units_at(bs, dest)
        if enemy_at_dest:
            return (
                f"Move {', '.join(names)} to {dest}.  "
                f"Opponent has {len(enemy_at_dest)} unit(s) there — Combat will be triggered."
            )
        return (
            f"Move {', '.join(names)} to {dest}.  No enemy units — "
            f"Non-Combat Showdown will occur; you will gain control if unopposed."
        )

    return f"Move '{action}' — no simulation available; general effect expected."


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
        "assessment": assessment,
    }


# ── Formatting helpers ────────────────────────────────────────────────────────


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
    return "\n".join(lines)


def _format_units(units: list[dict]) -> str:
    if not units:
        return "(none)"
    parts = []
    for u in units:
        status = []
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


def _find_hand_card(bs: dict, instance_id: str) -> Optional[dict]:
    for c in bs.get("my_hand", []):
        if c["instance_id"] == instance_id:
            return c
    return None


def _find_unit_anywhere(bs: dict, instance_id: str) -> Optional[dict]:
    for u in bs.get("my_base_units", []):
        if u["instance_id"] == instance_id:
            return u
    for u in bs.get("opponent_base_units", []):
        if u["instance_id"] == instance_id:
            return u
    for bf in bs.get("battlefields", []):
        for u in bf.get("my_units", []) + bf.get("opponent_units", []):
            if u["instance_id"] == instance_id:
                return u
    return None


def _enemy_units_at(bs: dict, battlefield_id: str) -> list[dict]:
    for bf in bs.get("battlefields", []):
        if bf["battlefield_id"] == battlefield_id:
            return bf.get("opponent_units", [])
    return []


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
