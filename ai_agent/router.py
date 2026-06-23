from __future__ import annotations

from pydantic import BaseModel, Field


class RouteDecision(BaseModel):
    forced_command: str | None = None
    modules: list[str] = Field(default_factory=list)
    needs_plan: bool = False
    strict_plan_check: bool = False


def route(brief_state: dict) -> RouteDecision:
    legal_moves = brief_state.get("legal_moves", []) or []
    decision_type = str(brief_state.get("decision_type", "")).lower()
    current_state = str(brief_state.get("current_state", "")).lower()

    if len(legal_moves) == 1:
        return RouteDecision(
            forced_command=legal_moves[0],
            modules=[],
            needs_plan=False,
            strict_plan_check=False,
        )

    modules = ["goal_and_role", "core_rules", "output_contract", "keywords_in_play"]
    if decision_type == "mulligan":
        modules.append("mulligan_guidance")
    if decision_type in ("showdown_focus", "combat_assignment"):
        modules.extend(["combat_rules_detailed", "priority_focus_rules"])
    elif decision_type == "chain_reaction" or "closed" in current_state:
        modules.append("priority_focus_rules")

    # Stable ordering and de-dup.
    modules = list(dict.fromkeys(modules))

    needs_plan = decision_type in ("main_phase", "showdown_focus")
    strict_plan_check = needs_plan

    return RouteDecision(
        forced_command=None,
        modules=modules,
        needs_plan=needs_plan,
        strict_plan_check=strict_plan_check,
    )
