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
import time
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


# Full candidate-line corpus (with per-line search_state) the search_for tool
# filters. Installed alongside the scout summaries; unlike _current_scout_lines
# this keeps the heavy search_state so predicate clauses can be resolved.
_current_search_corpus: list[dict] = []


def set_search_corpus(corpus: list[dict] | None) -> None:
    """Install the full candidate-line corpus for the search_for tool.

    Each entry is ``{line_id, moves, score, search_state}``. Called by
    agent.build_goal_overlay before the strategist runs; cleared (None) after so a
    later decision without a search never filters stale lines.
    """
    global _current_search_corpus
    _current_search_corpus = corpus or []


def _reasoner_context() -> Any:
    from .reasoner_context import current_context

    return current_context()


def _brief_state() -> dict:
    context = _reasoner_context()
    return context.brief_state if context is not None else _current_brief_state


def _scout_lines() -> list[dict]:
    context = _reasoner_context()
    return context.scout_lines if context is not None else _current_scout_lines


def _scout_stats() -> dict:
    context = _reasoner_context()
    return context.scout_stats if context is not None else _current_scout_stats


def _search_corpus() -> list[dict]:
    context = _reasoner_context()
    return context.search_corpus if context is not None else _current_search_corpus


# ── Read Skills ───────────────────────────────────────────────────────────────


def get_full_state() -> str:
    """Return the full board description for this seat as text."""
    context = _reasoner_context()
    if context is not None:
        return context.brief_state.get("full_state_text", "") or json.dumps(
            context.brief_state, indent=2
        )
    return _current_full_state_text or json.dumps(_current_brief_state, indent=2)


def get_zone(zone_id: str) -> str:
    """
    Return a focused description of one zone.
    zone_id examples: "my_hand", "my_base_units", "battlefield-a",
                      "opponent_base_units", "my_runes"
    """
    bs = _brief_state()
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
    bs = _brief_state()
    lines = [
        "Opponent public info:",
        f"  Score: {bs.get('opponent_score', '?')}",
        f"  Hand size: {bs.get('opponent_hand_size', '?')}",
        f"  Base units: {_format_units(bs.get('opponent_base_units', []))}",
    ]
    recent = ""
    context = _reasoner_context()
    memory = context.memory if context is not None else _current_memory
    game_id = context.game_id if context is not None else _current_game_id
    if memory is not None and game_id:
        recent = memory.opponent_actions_text(game_id)
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
    context = _reasoner_context()
    if context is not None:
        return list(context.brief_state.get("legal_moves", []) or [])
    return _current_legal_moves


def simulate_move(move: dict) -> dict:
    """
    Return the engine-truth result of playing this move, as structured facts.

    Phase 2: prefers a live POST /engine/simulate against Godot's pinned state.
    Falls back to the Phase-2.5 pre-sim lookup in brief_state when the engine
    server is unreachable (§6 fail-safe).
    """
    command = _move_to_command(move)
    live = _live_simulate([command])
    if live is not None:
        # Match the single-move SimResult shape (response_window singular).
        windows = live.get("opponent_windows", []) or []
        result = {
            "legal": live.get("legal", False),
            "source": "live_engine",
        }
        if live.get("error"):
            result["error"] = live["error"]
        if live.get("resolved_if_unanswered") is not None:
            result["resolved_if_unanswered"] = live["resolved_if_unanswered"]
        if windows:
            result["response_window"] = windows[0]
        if live.get("first_illegal_move") is not None:
            result["legal"] = False
        return result

    bs = _brief_state()
    sims = bs.get("move_simulations", {}) or {}

    if command in sims:
        out = dict(sims[command])
        out["source"] = "presim_lookup"
        return out

    # Not pre-simulated. Tell the model plainly rather than inventing an outcome.
    legal = command in (bs.get("legal_moves", []) or [])
    return {
        "legal": legal,
        "source": "unavailable",
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

    Phase 2: prefers live /engine/simulate; falls back to pre-sim line lookup.
    """
    commands = [_move_to_command(m) for m in (moves or [])]
    live = _live_simulate(commands)
    if live is not None:
        out = dict(live)
        out["source"] = "live_engine"
        return out

    bs = _brief_state()
    key = " ; ".join(commands)
    line_sims = bs.get("line_simulations", {}) or {}

    if key in line_sims:
        out = dict(line_sims[key])
        out["source"] = "presim_lookup"
        return out

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
            "source": "presim_lookup",
            "error": (
                "Only the first move of this line was simulated by the engine. "
                "Treat later steps as uncertain and hedge."
            ),
        }
    return {
        "legal": False,
        "applied_moves": [],
        "stopped_reason": "not_simulated",
        "source": "unavailable",
        "error": (
            f"No engine simulation available for the line '{key}'. "
            "Do not assert its outcome as fact."
        ),
    }


def _live_simulate(commands: list[str]) -> dict | None:
    """Try the live engine server; return None to fall back to pre-sim lookup."""
    if not commands:
        return None
    from .tool_budget import budget_exhausted_result, current_budget

    budget = current_budget()
    if budget is not None:
        if budget.exhausted:
            return budget_exhausted_result()
        key = tuple(commands)
        cached = budget.simulate_cache.get(key)
        if cached is not None:
            out = dict(cached)
            out["cached"] = True
            out.update(budget.status())
            return out
    try:
        from . import engine_client

        started = time.monotonic()
        result = engine_client.simulate(commands)
        if budget is not None:
            budget.engine_time_ms += max(0, int((time.monotonic() - started) * 1000))
            budget.simulate_cache[tuple(commands)] = dict(result)
            result = dict(result)
            result.update(budget.status())
        return result
    except Exception:
        # EngineUnavailable or unexpected — fail safe to Phase-1 lookup.
        return None


def search_for(
    constraints: list[dict] | None = None,
    combine: str = "all",
    top_n: int = 5,
    min_satisfaction: float = 0.0,
) -> dict[str, Any]:
    """Find candidate lines that achieve concrete, entity-scoped conditions.

    Each constraint is a clause ``{metric, comparator, threshold, target}`` over
    the concrete vocabulary (unit Might/health/alive, per-battlefield might &
    control, player score/hand/runes, this-turn tallies, card_played). Lines are
    ranked by combined satisfaction (``combine``: all=weakest-link / any / weighted)
    with a per-clause breakdown so you can see which condition binds.

    Phase 2: prefers a live /engine/search (fresh corpus + search_state), then
    filters in Python. Falls back to the Phase-1 pre-computed corpus when the
    engine server is unavailable.
    """
    from .schemas import PredicateClause
    from .search_metrics import run_search_for

    # Normalize each clause through PredicateClause (comparator + weight synonyms,
    # type coercion); drop structurally invalid ones rather than crashing.
    norm: list[dict] = []
    for c in constraints or []:
        if not isinstance(c, dict):
            continue
        try:
            norm.append(PredicateClause.model_validate(c).model_dump())
        except Exception:
            continue
    if not norm:
        return {
            "matches": [],
            "corpus_size": len(_search_corpus()),
            "source": "not_evaluated",
            "note": "search_for needs at least one valid constraint clause {metric, comparator, threshold, target}.",
        }

    corpus, source = _search_corpus_for_filter(top_n=max(top_n, 8))
    if not corpus:
        if source == "budget_exhausted":
            from .tool_budget import budget_exhausted_result

            return {
                "matches": [],
                "corpus_size": 0,
                **budget_exhausted_result(),
            }
        return {
            "matches": [],
            "corpus_size": 0,
            "source": source,
            "note": "No candidate lines available this turn. Use search_turn / evaluate_position instead.",
        }
    result = run_search_for(
        corpus, norm, combine=combine,
        top_n=top_n, min_satisfaction=min_satisfaction,
    )
    context = _reasoner_context()
    if context is not None:
        enriched: list[dict[str, Any]] = []
        for match in result.get("matches", []) or []:
            registered = context.registry.get(str(match.get("line_id", "")))
            if registered is not None:
                registered.update(match)
                enriched.append(registered)
            else:
                enriched.append(match)
        result["matches"] = enriched
    result["source"] = source
    from .tool_budget import current_budget
    from .investigation_metrics import classify_search_result

    budget = current_budget()
    if budget is not None:
        result.update(budget.status())
    scout_leader: tuple[str, ...] = ()
    if context is not None and context.scout_lines:
        scout_leader = tuple(
            str(m) for m in (context.scout_lines[0].get("moves", []) or [])
        )
    result["result_status"] = classify_search_result("search_for", result, scout_leader)
    return result


def _search_corpus_for_filter(top_n: int = 8) -> tuple[list[dict], str]:
    """Return (corpus, source) preferring a live engine search."""
    live = _live_search({
        "top_n": top_n,
        "budget": {
            "node_budget": 120,
            "time_budget_ms": 500,
            "max_depth": 8,
            "beam_width": 6,
        },
    })
    if live is not None and live.get("error") == "budget_exhausted":
        return [], "budget_exhausted"
    if live is not None and live.get("legal", True) is not False:
        lines = live.get("candidate_lines", []) or []
        context = _reasoner_context()
        if context is not None:
            call_index = int(context.telemetry.get("search_for_calls", 0)) + 1
            context.telemetry["search_for_calls"] = call_index
            lines = context.registry.register_many(
                lines, source=f"search-for-{call_index}"
            )
        corpus = [
            {
                "line_id": str(line.get("line_id", "")),
                "moves": list(line.get("moves", []) or []),
                "score": float(line.get("score", 0.0) or 0.0),
                "search_state": dict(line.get("search_state", {}) or {}),
                "move_contexts": list(line.get("move_contexts", []) or []),
                "expected_pre_hashes": list(line.get("expected_pre_hashes", []) or []),
                "root_state_hash": str(line.get("root_state_hash", "")),
                "legal": bool(line.get("legal", True)),
                "complete": bool(line.get("complete", False)),
                "terminal_reason": str(line.get("terminal_reason", "")),
                "search_mode": str(line.get("search_mode", "main")),
                "opponent_windows": list(line.get("opponent_windows", []) or []),
                "risk": dict(line.get("risk", {}) or {}),
                "cluster_key": str(line.get("cluster_key", "")),
                "cluster_size": int(line.get("cluster_size") or 1),
                "cluster_prefix_steps": int(line.get("cluster_prefix_steps") or 1),
            }
            for line in lines
            if isinstance(line, dict)
        ]
        if corpus:
            if context is not None:
                context.search_corpus = list(corpus)
            return corpus, "live_engine"
    current_corpus = _search_corpus()
    if current_corpus:
        return list(current_corpus), "presim_corpus"
    return [], "unavailable"


def _live_search(payload: dict) -> dict | None:
    from .tool_budget import budget_exhausted_result, current_budget

    budget = current_budget()
    actual_payload = payload
    if budget is not None:
        clamped = budget.clamp_search_payload(payload)
        if clamped is None:
            return budget_exhausted_result()
        actual_payload = clamped
    try:
        from . import engine_client

        started = time.monotonic()
        result = engine_client.search(actual_payload)
        if budget is not None:
            elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
            requested_nodes = int(
                (actual_payload.get("budget", {}) or {}).get("node_budget", 0) or 0
            )
            budget.record_search(result, elapsed_ms, requested_nodes)
            result = dict(result)
            result.update(budget.status())
        return result
    except Exception:
        return None


def deepen(
    line_id: str | None = None,
    extra_depth: int = 4,
    moves: list | None = None,
    prefix_steps: int | None = None,
) -> dict[str, Any]:
    """Re-search from an existing candidate line with more depth/budget.

    Pass ``line_id`` (resolved against the current search corpus) or an explicit
    ``moves`` prefix. Optional ``prefix_steps`` replays only the first *k*
    commands of ``line_id`` so TurnSearch can fork mid-line. Trailing
    ``end turn`` is stripped so the engine continues from the tip.
    """
    from .investigation_metrics import (
        classify_search_result,
        suggest_last_valid_prefix,
    )

    seed = _resolve_deepen_seed(line_id, moves, prefix_steps=prefix_steps)
    if seed is None:
        return {
            "legal": False,
            "candidate_lines": [],
            "error": (
                "deepen needs a known line_id from search_for/search_turn "
                "or an explicit moves prefix."
            ),
            "source": "unavailable",
            "result_status": "unavailable",
        }
    extra = max(1, int(extra_depth or 4))
    payload = {
        "seed_moves": seed,
        "top_n": 5,
        "budget": {
            "max_depth": 6 + extra,
            "node_budget": 80 + extra * 40,
            "time_budget_ms": 400 + extra * 100,
            "beam_width": 6,
        },
    }
    live = _live_search(payload)
    if live is None:
        return {
            "legal": False,
            "candidate_lines": [],
            "seed_moves": seed,
            "error": "Live engine unavailable; deepen requires /engine/search.",
            "source": "unavailable",
            "result_status": "unavailable",
            "prefix_steps": prefix_steps,
            "suggested_prefix": suggest_last_valid_prefix(seed),
        }
    if live.get("error") == "budget_exhausted":
        out_budget = dict(live)
        out_budget["seed_moves"] = seed
        out_budget["result_status"] = "unavailable"
        out_budget["prefix_steps"] = prefix_steps
        return out_budget
    out = dict(live)
    context = _reasoner_context()
    if context is not None:
        call_index = int(context.telemetry.get("deepen_calls", 0)) + 1
        context.telemetry["deepen_calls"] = call_index
        registered = context.registry.register_many(
            out.get("candidate_lines", []) or [],
            source=f"deepen-{call_index}",
        )
        out["candidate_lines"] = registered
        context.search_corpus = list(registered)
    out["seed_moves"] = seed
    out["source"] = out.get("source") or "live_engine"
    out["extra_depth"] = extra
    out["prefix_steps"] = prefix_steps
    stopped = str(out.get("stopped_reason", "") or "")
    error = str(out.get("error", "") or "")
    if stopped == "seed_failed" or "seed" in error.lower():
        out["legal"] = False
        out["result_status"] = "illegal_seed"
        out["suggested_prefix"] = suggest_last_valid_prefix(seed, error)
        return out

    scout_leader: tuple[str, ...] = ()
    if context is not None and context.scout_lines:
        scout_leader = tuple(
            str(m) for m in (context.scout_lines[0].get("moves", []) or [])
        )
    out["result_status"] = classify_search_result("deepen", out, scout_leader)
    return out


def expand_risk(
    line_id: str | None = None,
    card_id: str | None = None,
    moves: list | None = None,
    budget_ms: int = 300,
) -> dict[str, Any]:
    """Expand one risky line by searching recapture after an assumed interrupt."""
    line = _resolve_line_entry(line_id=line_id, moves=moves)
    if line is None:
        return {
            "ok": False,
            "error": "expand_risk needs a known line_id or explicit moves.",
            "source": "unavailable",
            "result_status": "unavailable",
        }
    picked_card_id = str(card_id or "")
    if not picked_card_id:
        threats = list((line.get("risk", {}) or {}).get("threats", []) or [])
        if threats:
            threats.sort(key=lambda t: float((t or {}).get("window_delta", 0.0) or 0.0), reverse=True)
            picked_card_id = str((threats[0] or {}).get("card_id", ""))
    payload: dict[str, Any] = {
        "line": line,
        "budget_ms": max(50, int(budget_ms or 300)),
    }
    if picked_card_id:
        payload["card_id"] = picked_card_id
    try:
        from . import engine_client

        out = engine_client.expand_risk(payload)
        out = dict(out)
        out["source"] = out.get("source") or "live_engine"
        out["line_id"] = out.get("line_id") or line.get("line_id", "")
        if picked_card_id:
            out["assumed_card"] = out.get("assumed_card") or picked_card_id
        return out
    except Exception:
        return {
            "ok": False,
            "error": "Live engine unavailable; expand_risk requires /engine/expand_risk.",
            "source": "unavailable",
            "result_status": "unavailable",
        }


def _resolve_line_entry(
    line_id: str | None = None,
    moves: list | None = None,
) -> dict[str, Any] | None:
    if line_id:
        target = str(line_id)
        context = _reasoner_context()
        if context is not None:
            reg = context.registry.get(target)
            if reg is not None:
                return dict(reg)
        for entry in _search_corpus():
            if str(entry.get("line_id", "")) == target:
                return dict(entry)
        for entry in _scout_lines():
            if str(entry.get("line_id", "")) == target:
                return dict(entry)
    if moves:
        cmds = [_move_to_command(m) for m in moves]
        return {
            "line_id": "ad_hoc",
            "moves": cmds,
            "opponent_windows": [],
            "resolved_state": {},
            "cluster_key": "",
        }
    return None


def _resolve_deepen_seed(
    line_id: str | None,
    moves: list | None,
    *,
    prefix_steps: int | None = None,
) -> list[str] | None:
    cmds: list[str] = []
    if moves:
        cmds = [_move_to_command(m) for m in moves]
    elif line_id:
        target = str(line_id)
        context = _reasoner_context()
        if context is not None:
            registered = context.registry.get(target)
            if registered is not None:
                cmds = [str(m) for m in (registered.get("moves", []) or [])]
        for entry in _search_corpus():
            if str(entry.get("line_id", "")) == target:
                cmds = [str(m) for m in (entry.get("moves", []) or [])]
                break
        if not cmds:
            for entry in _scout_lines():
                if str(entry.get("line_id", "")) == target:
                    cmds = [str(m) for m in (entry.get("moves", []) or [])]
                    break
        if cmds and prefix_steps is not None:
            steps = max(0, int(prefix_steps))
            if steps <= 0:
                return None
            cmds = cmds[:steps]
    if not cmds:
        return None
    # Drop trailing end-turn so search can still expand from the tip.
    while cmds and cmds[-1].strip().lower() == "end turn":
        cmds.pop()
    return cmds or None


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
    scout_lines = _scout_lines()
    if not scout_lines:
        return {
            "lines": [],
            "note": (
                "No scout search available this turn. Ground goals with "
                "evaluate_position and the board summary instead."
            ),
        }
    return {
        "lines": scout_lines[: max(1, int(top_n or 5))],
        "search_stats": _scout_stats(),
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
    bs = _brief_state()
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
