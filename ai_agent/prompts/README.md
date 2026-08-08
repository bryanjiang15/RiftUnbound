# AI Prompts

Every **static** (placeholder-free) prompt the agent sends to the model lives here
as a Markdown file. Code loads them by name via `load_prompt(...)` from
`ai_agent/prompts/__init__.py`, so prompt wording is edited in one place instead of
being buried in Python string literals.

Prompts that need runtime substitution (board state, tool context, card ids) are
still assembled in code and are intentionally **not** stored here.

## Files

| File | Loaded by | Purpose |
| --- | --- | --- |
| `output_contract.md` | `system_prompt.py` | Required JSON output shape + action list |
| `core_rules.md` | `system_prompt.py` | Always-on Riftbound core rules |
| `combat_rules_detailed.md` | `system_prompt.py` | Detailed combat module (showdowns) |
| `priority_focus_rules.md` | `system_prompt.py` | Turn-state / priority / focus module |
| `mulligan_guidance.md` | `system_prompt.py` | Opening-hand guidance module |
| `goal_and_role.md` | `system_prompt.py` | Agent goal, role, and behavioral guidance |
| `planner_role_preamble.md` | `planner.py` | Turn-planner role preamble |
| `planner_schema_retry.md` | `planner.py` | Retry nudge when a plan fails schema |
| `strategist_role_base.md` | `strategist.py` | Turn-strategist role |
| `strategist_output_discipline_think.md` | `strategist.py` | Think-phase output discipline |
| `strategist_format_phase.md` | `strategist.py` | Format-phase GoalSet instruction |
| `strategist_task.md` | `strategist.py` | Strategist user-prompt task line |
| `reasoner_role_base.md` | `reasoner.py` | Phase-3 Reasoner role, scope, and safe-fallback stance |
| `reasoner_output_discipline_think.md` | `reasoner.py` | Reasoner think-phase investigation discipline |
| `reasoner_format_phase.md` | `reasoner.py` | Terminal `commit_line` / `emit_goals` output instruction |
| `reasoner_task.md` | `reasoner.py` | Reasoner user-prompt task line |
| `line_selector_retry.md` | `agent.py` | Retry nudge for the line selector |

## Usage

```python
from .prompts import load_prompt

CORE_RULES = load_prompt("core_rules")
```

`load_prompt` reads `<name>.md` from this folder, trims surrounding whitespace, and
caches the result.
