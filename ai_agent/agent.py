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
from typing import Any, Optional

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from . import skills as skill_module
from .memory import Memory
from .schemas import Decision, Move
from .system_prompt import build_system_prompt

logger = logging.getLogger(__name__)

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

    # Inject memory slice
    mem_slice = memory.recent_slice(game_id)
    if mem_slice:
        messages.append({"role": "user", "content": mem_slice})

    # Brief state as the main user message
    brief_summary = _format_brief_state(brief_state)
    user_content = f"## Current Decision\n\n{brief_summary}"
    if rejection_context:
        user_content += (
            f"\n\n## Previous Move Was Rejected\n"
            f"Rejected move: {json.dumps(rejection_context.get('rejected_move', {}))}\n"
            f"Reason: {rejection_context.get('rejection_reason', 'unknown')}\n"
            f"Please choose a different legal move."
        )
    messages.append({"role": "user", "content": user_content})

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

    # Resources
    lines.append(f"Energy: {bs.get('my_energy', 0)} | Power: {bs.get('my_power', {})}")
    rune_strs = [
        f"rune-{r['rune_index']}({r['domain']}{'*' if r['is_exhausted'] else ''})"
        for r in bs.get("my_runes", [])
    ]
    if rune_strs:
        lines.append(f"Runes: {', '.join(rune_strs)}")
    lines.append("")

    # Hand
    hand = bs.get("my_hand", [])
    lines.append(f"Hand ({len(hand)} cards):")
    for c in hand:
        cost = f"{c.get('energy_cost', 0)}E"
        if c.get("power_cost"):
            cost += "+" + "+".join(f"{pc['amount']}{pc['domain'][:3].upper()}" for pc in c["power_cost"])
        kw = ", ".join(c.get("keywords", []))
        might_str = f" Might:{c['might']}" if c.get("might") is not None else ""
        lines.append(f"  {c['instance_id']} — {c['name']} [{c['card_type']}] ({cost}){might_str} {kw}")
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

    # Decision context
    if bs.get("pending_choice_options"):
        lines.append(f"Pending choice options: {bs['pending_choice_options']}")
    if bs.get("combat_assignment_active"):
        lines.append(f"Combat assignment active. Remaining attacker might: {bs.get('remaining_attacker_might', 0)}")
        lines.append(f"Already assigned: {bs.get('damage_assigned', {})}")

    return "\n".join(lines)
