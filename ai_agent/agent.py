"""
Riftbound AI Agent — Reasoning Loop

This module owns the ~150-line loop that:
  1. Assembles context from system prompt, memory, and brief state.
  2. Calls the OpenAI chat completions API with the skill tool set.
  3. Dispatches any tool calls the model makes (read / helper skills).
  4. Validates that the final output conforms to the Decision schema.
  5. Falls back to "pass" after MAX_TOOL_ROUNDS or on unrecoverable error.

The loop is intentionally kept explicit and debuggable — no framework magic.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from . import skills as skill_module
from .memory import Memory
from .schemas import Decision, Move
from .system_prompt import build_system_prompt

logger = logging.getLogger(__name__)

_INPUT_LOG_PATH = Path(__file__).resolve().parent / "agent_inputs.log"
_LOG_INPUTS: bool = os.environ.get("RIFTBOUND_LOG_INPUTS", "0").strip() not in ("0", "", "false", "no")

# Maximum tool-call rounds before we give up and emit a decision
MAX_TOOL_ROUNDS = 6
# Model to use (can be overridden via RIFTBOUND_AI_MODEL env var)
DEFAULT_MODEL = "gpt-4o"

_client: Optional[AsyncOpenAI] = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


# ── Tool definitions (OpenAI tool-call format) ────────────────────────────────

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_legal_moves",
            "description": (
                "Return the current enumerated list of legal command strings for "
                "this decision point. Call this when you want a concrete option set "
                "to reason over. The brief state already includes one, but this is "
                "always fresh."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_full_state",
            "description": (
                "Return the full board description for this seat. Useful when the "
                "brief state summary is not enough detail."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_zone",
            "description": (
                "Return a focused description of one zone. "
                "zone_id choices: 'my_hand', 'my_base_units', 'opponent_base_units', "
                "'my_runes', 'battlefield-a', 'battlefield-b'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "zone_id": {"type": "string", "description": "The zone to inspect."}
                },
                "required": ["zone_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_card_detail",
            "description": (
                "Return the full card definition (text, stats, keywords, abilities) "
                "for a card by its instance_id or base card id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "card_id": {"type": "string", "description": "The card instance_id or base id."}
                },
                "required": ["card_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_opponent_history",
            "description": "Return a summary of what the opponent has done this game.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_rule",
            "description": (
                "Search the Riftbound implementation rules for a topic or keyword. "
                "Call this when uncertain about a rules interaction rather than guessing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic, keyword, or rules question."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_move",
            "description": (
                "Apply a hypothetical move to a copy of the brief state and report "
                "the expected result. No real game effect. Use to check a line one ply deep."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "move": {
                        "type": "object",
                        "description": "A move object with 'action' and 'parameters' fields.",
                        "properties": {
                            "action": {"type": "string"},
                            "parameters": {"type": "object"},
                        },
                        "required": ["action"],
                    }
                },
                "required": ["move"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_position",
            "description": (
                "Return a heuristic assessment of the current board position: "
                "score advantage, unit counts, battlefield control, and overall outlook."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


# ── Skill dispatch ────────────────────────────────────────────────────────────


def _dispatch_tool(name: str, arguments: dict) -> Any:
    if name == "list_legal_moves":
        return skill_module.list_legal_moves()
    if name == "get_full_state":
        return skill_module.get_full_state()
    if name == "get_zone":
        return skill_module.get_zone(arguments.get("zone_id", ""))
    if name == "get_card_detail":
        return skill_module.get_card_detail(arguments.get("card_id", ""))
    if name == "get_opponent_history":
        return skill_module.get_opponent_history()
    if name == "lookup_rule":
        return skill_module.lookup_rule(arguments.get("query", ""))
    if name == "simulate_move":
        return skill_module.simulate_move(arguments.get("move", {}))
    if name == "evaluate_position":
        return skill_module.evaluate_position()
    return f"Unknown skill: {name}"


# ── Decision parsing ──────────────────────────────────────────────────────────


def _parse_decision(content: str) -> Optional[Decision]:
    """Try to parse the model's text response as a Decision JSON object."""
    content = content.strip()
    # Strip markdown fences if present
    if content.startswith("```"):
        content = "\n".join(
            line for line in content.splitlines()
            if not line.strip().startswith("```")
        ).strip()
    try:
        data = json.loads(content)
        return Decision.model_validate(data)
    except Exception as exc:
        logger.warning("Decision parse failed: %s", exc)
        return None


_PASS_DECISION = Decision(
    reasoning="Fallback: could not produce a valid decision within retry budget.",
    move=Move(action="pass"),
)


def _log_input(game_id: str, brief_state: dict, messages: list) -> None:
    """Write a snapshot of the full agent input to agent_inputs.log."""
    if not _LOG_INPUTS:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sep = "─" * 72
    lines = [
        "",
        sep,
        f"Turn {brief_state.get('turn_number', '?')}  "
        f"Type: {brief_state.get('decision_type', '?')}  "
        f"Game: {game_id}  [{ts}]",
        sep,
    ]
    for msg in messages:
        role = msg.get("role", "?").upper()
        content = msg.get("content") or ""
        if content:
            lines.append(f"[{role}]")
            lines.append(content)
            lines.append("")
    try:
        with _INPUT_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as exc:
        logger.warning("Input log write failed: %s", exc)


# ── Main reasoning loop ───────────────────────────────────────────────────────


async def decide(
    brief_state: dict,
    game_id: str,
    memory: Memory,
    rejection_context: Optional[dict] = None,
) -> Decision:
    """
    Given a BriefState dict, run the agent loop and return a Decision.
    rejection_context is non-None on a retry after a Godot rejection.
    """
    model = os.environ.get("RIFTBOUND_AI_MODEL", DEFAULT_MODEL)
    system = build_system_prompt()

    # Assemble initial messages
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system},
    ]

    # Inject own decision history for this game
    mem_slice = memory.recent_slice(game_id)
    if mem_slice:
        messages.append({"role": "user", "content": mem_slice})

    # Inject opponent action history for this game
    opp_slice = memory.opponent_slice(game_id)
    if opp_slice:
        messages.append({"role": "user", "content": opp_slice})

    # Brief state as the main user message
    brief_summary = _format_brief_state(brief_state)
    user_content = f"## Current Decision\n\n{brief_summary}"
    if rejection_context:
        user_content += (
            f"\n\n## Previous Move Was Rejected\n"
            f"Rejected move: {json.dumps(rejection_context.get('rejected_move', {}))}\n"
            f"Reason: {rejection_context.get('rejection_reason', 'unknown')}\n"
            f"In one sentence, state what you misunderstood or assumed incorrectly. "
            f"Then produce a corrected move."
        )
    messages.append({"role": "user", "content": user_content})

    # Optionally record full input for debugging (set RIFTBOUND_LOG_INPUTS=1)
    _log_input(game_id, brief_state, messages)

    # Tool-use loop
    for round_num in range(MAX_TOOL_ROUNDS):
        try:
            response = await get_client().chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,  # type: ignore[arg-type]
                tool_choice="auto",
                temperature=0.3,
                response_format={"type": "text"},
            )
        except Exception as exc:
            logger.error("OpenAI API error: %s", exc)
            return _PASS_DECISION

        choice = response.choices[0]
        msg = choice.message

        # Tool calls — dispatch and loop
        if msg.tool_calls:
            messages.append(msg)  # type: ignore[arg-type]
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = _dispatch_tool(tc.function.name, args)
                result_text = json.dumps(result) if not isinstance(result, str) else result
                logger.debug("Tool %s → %s", tc.function.name, result_text[:200])
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })
            continue

        # No tool calls — attempt to parse as Decision
        content = msg.content or ""
        decision = _parse_decision(content)
        if decision is not None:
            logger.info(
                "Decision [round=%d]: action=%s reasoning=%.120s",
                round_num,
                decision.move.action,
                decision.reasoning,
            )
            return decision

        # Model responded with text but not valid JSON — prompt it to fix
        logger.warning("Round %d: model response not valid JSON, prompting fix.", round_num)
        messages.append({"role": "assistant", "content": content})
        messages.append({
            "role": "user",
            "content": (
                "Your response was not valid JSON matching the required schema. "
                "Please respond with only the JSON Decision object. "
                "No markdown, no explanation text — raw JSON only."
            ),
        })

    logger.warning("Exhausted %d rounds without a valid decision — returning pass.", MAX_TOOL_ROUNDS)
    return _PASS_DECISION


# ── Brief state formatting ────────────────────────────────────────────────────


def _format_brief_state(bs: dict) -> str:
    """Render the brief state as a readable text summary for the model."""
    lines: list[str] = []

    lines.append(f"Turn {bs.get('turn_number', '?')} | "
                 f"Phase: {bs.get('current_phase', '?')} | "
                 f"State: {bs.get('current_state', '?')} | "
                 f"Decision type: **{bs.get('decision_type', '?')}**")
    lines.append(f"My score: {bs.get('my_score', 0)} | "
                 f"Opponent score: {bs.get('opponent_score', 0)} | "
                 f"Victory: 8 pts")
    lines.append("")

    # Resources — compute total playable energy from pool + untapped runes
    runes = bs.get("my_runes", [])
    untapped_runes = [r for r in runes if not r.get("is_exhausted", False)]
    exhausted_runes = [r for r in runes if r.get("is_exhausted", False)]
    pool_energy = bs.get("my_energy", 0)
    pool_power: dict = bs.get("my_power", {}) or {}
    total_energy = pool_energy + len(untapped_runes)

    # Domain power available = pool power + one per untapped rune of that domain
    total_power: dict[str, int] = dict(pool_power)
    for r in untapped_runes:
        d = r.get("domain", "")
        total_power[d] = total_power.get(d, 0) + 1

    # Compact rune summary: "3 untapped (1 fury, 2 mind) | 1 exhausted (1 fury)"
    untapped_by_domain: dict[str, int] = {}
    for r in untapped_runes:
        d = r.get("domain", "")
        untapped_by_domain[d] = untapped_by_domain.get(d, 0) + 1
    exhausted_by_domain: dict[str, int] = {}
    for r in exhausted_runes:
        d = r.get("domain", "")
        exhausted_by_domain[d] = exhausted_by_domain.get(d, 0) + 1
    untapped_summary = ", ".join(
        f"{n} {d}" for d, n in sorted(untapped_by_domain.items())
    ) or "none"
    exhausted_summary = ", ".join(
        f"{n} {d}" for d, n in sorted(exhausted_by_domain.items())
    )
    rune_summary = f"{len(untapped_runes)} untapped ({untapped_summary})"
    if exhausted_runes:
        rune_summary += f" | {len(exhausted_runes)} exhausted ({exhausted_summary})"
    power_str = (
        "  " + " ".join(f"{d.upper()[:3]}×{n}" for d, n in sorted(total_power.items()))
        if total_power else ""
    )
    lines.append(f"Resources: {total_energy}E playable{power_str}  [{rune_summary}]")

    # Floating energy/power: only shown when the pool has non-zero values from
    # card effects or abilities (rare — normally the pool is empty at Main Phase).
    floating_power = {d: v for d, v in pool_power.items() if v > 0}
    if pool_energy > 0 or floating_power:
        extra_parts = []
        if pool_energy > 0:
            extra_parts.append(f"+{pool_energy}E")
        for d, v in sorted(floating_power.items()):
            extra_parts.append(f"+{v} {d.upper()[:3]}")
        lines.append(f"  (includes {' '.join(extra_parts)} floating from card/ability effects)")

    lines.append("")

    # Hand — annotate each card with affordability given rune situation
    hand = bs.get("my_hand", [])
    lines.append(f"Hand ({len(hand)} cards):")
    for c in hand:
        e_cost = c.get("energy_cost", 0)
        p_costs: list = c.get("power_cost", []) or []
        cost_str = f"{e_cost}E"
        if p_costs:
            cost_str += "+" + "+".join(
                f"{pc['amount']}{pc['domain'][:3].upper()}" for pc in p_costs
            )
        kw = ", ".join(c.get("keywords", []))
        might_str = f" Might:{c['might']}" if c.get("might") is not None else ""
        # Affordability: check energy and each domain power requirement
        energy_ok = e_cost <= total_energy
        domain_ok = all(
            total_power.get(pc["domain"], 0) >= pc["amount"] for pc in p_costs
        )
        playable = "[PLAYABLE]" if (energy_ok and domain_ok) else "[too costly]"
        lines.append(
            f"  {c['instance_id']} — {c['name']} [{c['card_type']}] ({cost_str})"
            f"{might_str} {playable} {kw}"
        )
        effect = c.get("effect_text", "")
        if effect:
            lines.append(f"    Effect: {skill_module.format_effect_text(effect)}")
    lines.append("")

    # Board
    my_base = bs.get("my_base_units", [])
    if my_base:
        lines.append("My base units: " + ", ".join(
            f"{u['instance_id']}({u['current_might']}MHT{'*' if u['is_exhausted'] else ''})"
            for u in my_base
        ))
    opp_base = bs.get("opponent_base_units", [])
    if opp_base:
        lines.append("Opponent base units: " + ", ".join(
            f"{u['instance_id']}({u['current_might']}MHT{'*' if u['is_exhausted'] else ''})"
            for u in opp_base
        ))
    lines.append(f"Opponent hand size: {bs.get('opponent_hand_size', 0)}")
    lines.append("")

    # Battlefields
    for bf in bs.get("battlefields", []):
        ctrl = bf.get("controller_index", -1)
        ctrl_str = "uncontrolled" if ctrl == -1 else f"P{ctrl + 1}"
        contested = " CONTESTED" if bf.get("is_contested") else ""
        lines.append(f"[{bf['battlefield_id']}] {bf['display_name']} — {ctrl_str}{contested}")
        bf_effect = bf.get("effect_text", "")
        if bf_effect:
            lines.append(f"  Effect: {skill_module.format_effect_text(bf_effect)}")
        if bf.get("my_units"):
            lines.append("  My units: " + ", ".join(
                f"{u['instance_id']}({u['current_might']}MHT)" for u in bf["my_units"]
            ))
        if bf.get("opponent_units"):
            lines.append("  Opp units: " + ", ".join(
                f"{u['instance_id']}({u['current_might']}MHT)" for u in bf["opponent_units"]
            ))
    lines.append("")

    # Legal moves
    legal = bs.get("legal_moves", [])
    if legal:
        shown = legal[:20]
        lines.append(f"Legal moves ({len(legal)} total, first {len(shown)} shown):")
        for mv in shown:
            lines.append(f"  {mv}")
        if len(legal) > 20:
            lines.append(f"  ... and {len(legal) - 20} more (call list_legal_moves)")

    # Decision context — pending choice
    ctx = bs.get("pending_choice_context", {})
    opts = bs.get("pending_choice_options", [])
    if ctx or opts:
        lines.append("")
        lines.append("=== PENDING CHOICE ===")
        if ctx.get("prompt_text"):
            lines.append(f"What: {ctx['prompt_text']}")
        if ctx.get("source_card_name"):
            lines.append(f"Source: {ctx['source_card_name']} (id: {ctx.get('source_card_id', '?')})")
        if ctx.get("source_effect_text"):
            lines.append(
                f"Source effect: {skill_module.format_effect_text(str(ctx['source_effect_text']))}"
            )
        if ctx.get("ability_description"):
            lines.append(f"Ability: {ctx['ability_description']}")
        if opts:
            lines.append(f"Options (use choose <option>): {opts}")
        lines.append("======================")

    if bs.get("combat_assignment_active"):
        lines.append(f"Combat assignment active. Remaining attacker might: {bs.get('remaining_attacker_might', 0)}")
        lines.append(f"Already assigned: {bs.get('damage_assigned', {})}")

    return "\n".join(lines)
