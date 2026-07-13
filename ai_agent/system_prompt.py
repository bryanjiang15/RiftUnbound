"""
Riftbound AI Agent — System Instruction (state-aware / layered)

The system prompt is assembled per decision from a stable CORE plus conditional
modules selected by the current decision type and game state.  This keeps each
turn's prompt focused and cheap: a main-phase decision does not carry the full
combat damage model, and a combat decision gets MORE detail than a flat prompt
could afford.

Always included:  GOAL_AND_ROLE, CORE_RULES, OUTPUT_CONTRACT.
Conditional:      COMBAT_RULES_DETAILED, PRIORITY_FOCUS_RULES, MULLIGAN_GUIDANCE,
                  and only the keyword glossary entries for keywords in play.

Anything trimmed from the prompt stays reachable through the lookup_rule and
get_keyword skills, so no rule is ever lost — it is just loaded on demand.
"""

from .prompts import load_prompt

OUTPUT_CONTRACT = load_prompt("output_contract")

CORE_RULES = load_prompt("core_rules")

COMBAT_RULES_DETAILED = load_prompt("combat_rules_detailed")

PRIORITY_FOCUS_RULES = load_prompt("priority_focus_rules")

MULLIGAN_GUIDANCE = load_prompt("mulligan_guidance")

# Keyword glossary — only the entries for keywords actually in play are injected.
KEYWORD_GLOSSARY: dict[str, str] = {
    "assault": "Assault [X]: +X Might while attacking.",
    "shield": "Shield [X]: +X Might while defending.",
    "tank": "Tank: must be assigned lethal damage before non-Tank friendly units.",
    "ganking": "Ganking: unit may Standard Move Battlefield -> Battlefield.",
    "accelerate": "Accelerate: pay +1 Energy +1 Power to enter Ready instead of Exhausted.",
    "legion": "Legion: cost reduced by 2 if you played another card this turn.",
    "reaction": "Reaction: can be played during Closed states on any player's turn.",
    "action": "Action: can be played during Showdown Open states.",
    "hidden": (
        "Hidden: from hand at a controlled battlefield, use hide_card (not play_card). "
        "Hiding costs 0 Energy +1 any-domain Power (recycle a rune). Once face-down, "
        "play_card with from_hidden: true costs 0 Energy and 0 Power — the printed cost "
        "does not apply. Only use from_hidden for a card already at a battlefield "
        "(legal_moves: \"play <id> from hidden\")."
    ),
    "deflect": "Deflect [X]: enemy spells/abilities targeting this cost X more Power.",
    "deathknell": "Deathknell: triggers when the unit dies.",
    "stun": "Stun: a stunned unit contributes no Might in the Combat Damage Step; clears at the next Ending Step.",
}

GOAL_AND_ROLE = load_prompt("goal_and_role")


def _collect_keywords(brief_state: dict) -> list[str]:
    """Scan all visible zones for keywords present in this brief state."""
    found: set[str] = set()

    def add_from(items) -> None:
        for it in items or []:
            if not isinstance(it, dict):
                continue
            for kw in it.get("keywords", []) or []:
                if isinstance(kw, str):
                    found.add(kw.strip().lower())

    add_from(brief_state.get("my_hand"))
    add_from(brief_state.get("my_base_units"))
    add_from(brief_state.get("opponent_base_units"))
    champ = brief_state.get("my_champion")
    if isinstance(champ, dict):
        add_from([champ])
    for bf in brief_state.get("battlefields", []) or []:
        if not isinstance(bf, dict):
            continue
        add_from(bf.get("my_units"))
        add_from(bf.get("opponent_units"))
        fd = bf.get("my_facedown")
        if isinstance(fd, dict):
            add_from([fd])

    return [kw for kw in KEYWORD_GLOSSARY if kw in found]


def _keyword_glossary_block(brief_state: dict) -> str:
    kws = _collect_keywords(brief_state)
    if not kws:
        return ""
    lines = ["## Keywords in play"]
    lines.extend(f"- {KEYWORD_GLOSSARY[kw]}" for kw in kws)
    return "\n".join(lines)


PROMPT_MODULES: dict[str, str] = {
    "goal_and_role": GOAL_AND_ROLE,
    "core_rules": CORE_RULES,
    "output_contract": OUTPUT_CONTRACT,
    "combat_rules_detailed": COMBAT_RULES_DETAILED,
    "priority_focus_rules": PRIORITY_FOCUS_RULES,
    "mulligan_guidance": MULLIGAN_GUIDANCE,
}


def goal_vocabulary_block() -> str:
    """The strategist's goal menu: exactly what a GoalSet may reference.

    Generated from the goal compiler's own whitelists (registry weights +
    state_target metrics) so the options offered to the LLM can never drift from
    what the compiler will accept. Anything off this menu compiles to a no-op, so
    naming a real metric here is what makes a goal take effect.

    This is the deliberate answer to "how much context does the strategist need":
    NOT more rules (combat math / priority timing stay tactical, owned by the
    search and reachable via lookup_rule) — a structured vocabulary of what a goal
    can express.
    """
    # Local import avoids any import-time coupling; goal_compiler only needs schemas.
    from .goal_compiler import STATE_TARGET_METRICS, weight_bias_features

    wb = weight_bias_features()
    weight_lines = (
        "\n".join(f"  - {sid}" for sid in sorted(wb))
        if wb else "  (registry manifest unavailable — weight_bias goals will no-op)"
    )
    metric_lines = "\n".join(
        f"  - {m}{' [needs metric_key = a battlefield id]' if is_dict else ''}: {meaning}"
        for m, (is_dict, meaning) in STATE_TARGET_METRICS.items()
    )
    return (
        "## Goal vocabulary — what a GoalSet may reference\n"
        "Propose at most 4 goals. Each goal must use ONE kind below and reference\n"
        "ONLY the listed ids/metrics; anything else is ignored by the compiler. You\n"
        "set WHAT to want and a coarse `priority` (low|med|high); the engine sets the\n"
        "magnitudes — never write raw weights.\n\n"
        "### kind = weight_bias (generic lean — scale an existing scoring term)\n"
        "Fields: feature (one id below), optional multiplier (0.5–2.5; else priority\n"
        "picks it). Use for broad turns: develop, contest control, push removal.\n"
        f"{weight_lines}\n\n"
        "### kind = state_target (specific objective — reward reaching a board state)\n"
        "Fields: metric (one below), metric_key (battlefield id, only where noted),\n"
        "comparator (>= | <= | ==), threshold (number). Compiled to a GRADED bonus,\n"
        "so progress toward the threshold is rewarded, not only the exact hit.\n"
        f"{metric_lines}\n\n"
        "### kind = card_target (specific — reward playing a named card this turn)\n"
        "Fields: card_id (a hand instance id you confirmed with get_card_detail).\n"
    )


def build_system_prompt_from_modules(
    modules: list[str],
    brief_state: dict | None = None,
) -> str:
    brief_state = brief_state or {}
    parts: list[str] = []
    for module in modules:
        block = PROMPT_MODULES.get(module, "")
        if block:
            parts.append(block)
    if "keywords_in_play" in modules:
        glossary = _keyword_glossary_block(brief_state)
        if glossary:
            parts.append(glossary)
    if "goal_vocabulary" in modules:
        parts.append(goal_vocabulary_block())
    return "\n\n".join(p.strip() for p in parts if p.strip()).strip()


def build_system_prompt(brief_state: dict | None = None) -> str:
    """
    Assemble the system prompt for this decision.

    The stable CORE (goal/role, core rules, output contract) always comes first so
    any prompt-prefix caching keeps a constant prefix.  Conditional modules are
    appended only when the decision type or game state calls for them.
    """
    brief_state = brief_state or {}
    decision_type = str(brief_state.get("decision_type", "")).lower()
    current_state = str(brief_state.get("current_state", "")).lower()

    in_showdown = "showdown" in current_state or decision_type in (
        "combat_assignment",
        "showdown_focus",
    )
    in_closed_or_chain = (
        "closed" in current_state
        or "showdown" in current_state
        or decision_type in ("chain_reaction", "showdown_focus", "combat_assignment")
    )

    return build_system_prompt_from_modules(
        modules=[
            "goal_and_role",
            "core_rules",
            "output_contract",
            *(
                ["combat_rules_detailed"]
                if in_showdown
                else []
            ),
            *(
                ["priority_focus_rules"]
                if in_closed_or_chain
                else []
            ),
            *(
                ["mulligan_guidance"]
                if decision_type == "mulligan"
                else []
            ),
            "keywords_in_play",
        ],
        brief_state=brief_state,
    )
