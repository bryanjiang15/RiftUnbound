# Riftbound Coding Style

Conventions for the Godot 4.6 TCG simulation, Python AI agent, and tooling scripts.
When editing existing code, match the surrounding file; apply these rules to new code
and to files you touch for other reasons.

See also: `.cursor/rules/riftbound-project.mdc` (architecture), `Docs/Game Rules/`
(authoritative rules behavior).

---

## Repository layout

| Path | Role |
|------|------|
| `Scripts/Domain/` | Pure state models — no UI, no logging, no `Node` types |
| `Scripts/Game/` | Rules engine: processors, resolvers, cost payment |
| `Scripts/Data/` | JSON loading, `CardDefinition`, deck files |
| `Scripts/UI/` | Presentation — reads `GameState`, submits commands via `GameController` |
| `Scripts/Tests/Tcg/` | Headless tests via `TcgTestHarness` + JSON fixtures |
| `Scripts/AI/` | AI sidecar (HTTP agent + heuristic fallback) |
| `Scripts/bugs/` | Python bug backlog tooling |
| `ai_agent/` | FastAPI OpenAI service |
| `Data/Cards/*.json` | Card definitions |

**Boundaries**

- Game logic lives in `Domain/` + `Game/`, never in UI scripts.
- UI calls `GameController.submit_command()` or reads `gs`; it does not implement rules.
- Pass `controller: GameController` into processors only when prompts, discard choice,
  or auto-pay are needed.
- Always pay costs through `GameController.try_pay_cost()`, never `CostCalculator.pay_cost()`
  directly (except inside `try_pay_cost`, manual `recycle rune-N`, or `_auto_recycle_rune`).

---

## GDScript naming

| Item | Convention | Example |
|------|------------|---------|
| `class_name` | PascalCase | `ChainProcessor` |
| File name | Match class | `ChainProcessor.gd` |
| Public functions | `snake_case` | `submit_command()` |
| Private helpers | `_snake_case` | `_cmd_play()` |
| Constants | `SCREAMING_SNAKE` | `MAX_LOG_LINES` |
| JSON / card definition IDs | kebab-case | `flame-chompers` |
| Runtime instance IDs | definition ID; dupes get `-2`, `-3` | `fury-rune-2` |
| Rune console IDs | index in channeled runes | `rune-0`, `rune-1` |

**Domain abbreviations** (engine code only — use consistently):

| Abbrev | Meaning |
|--------|---------|
| `gs` | `GameState` |
| `ps` | `PlayerState` |
| `pi` | player index (0 or 1) |
| `ab` | ability dictionary from JSON |
| `bf` | battlefield |

Scene-attached scripts that are not reused (`GameScene.gd`) may omit `class_name`.
Reusable types always declare `class_name`.

---

## Typing

- Annotate function parameters and return types.
- Prefer typed collections when the element type is known:

```gdscript
var log_lines: Array[String] = []
var players: Array[PlayerState] = []
var hand: Array[CardInstance] = []
```

- Use `Variant` at JSON boundaries; narrow with `is` / `match` immediately.
- Card abilities stay as `Dictionary` (schema-driven JSON); do not wrap in classes unless
  the schema itself changes.

---

## Dependencies

Default to global `class_name` references:

```gdscript
var gs: GameState = GameState.new()
var ability_resolver: AbilityResolver = AbilityResolver.new()
```

Preload only to break circular references:

```gdscript
const ConditionEvaluatorScript = preload("res://Scripts/Game/ConditionEvaluator.gd")
```

When preloading, type the variable:

```gdscript
var trigger_dispatcher: TriggerDispatcher = TriggerDispatcherScript.new()
```

---

## Processor pattern

Stateless rule steps use static utility classes:

```gdscript
class_name ChainProcessor

static func handle_pass(gs: GameState, ability_resolver: AbilityResolver, controller: GameController = null) -> Array[String]:
    var log_lines: Array[String] = []
    # mutate gs in place
    return log_lines
```

- Mutate `gs` in place; return `Array[String]` log lines.
- Keep processors focused — one file per concern (`ChainProcessor`, `CombatProcessor`, …).

---

## Console log protocol

All player-facing output goes through `GameController._log()`, not `print()`.

| Tag | Meaning |
|-----|---------|
| `[ERROR]` | Command rejected; sets `last_command_error = true` |
| `[PROMPT]` | Awaiting player input |
| `[INFO]` | Non-fatal engine notice (e.g. unhandled `effect_type`) |
| `> …` | Game event narration |
| `[P1] > cmd` | Echo of a submitted command |

---

## Adding card behavior

1. Define ability in `Data/Cards/*.json` (`effect_type`, `timing`, `cost`, `effect_params`).
2. Add handler in `AbilityResolver.gd` `match effect_type`.
3. Register in `Docs/Game Rules/riftbound-card-data-schema.md`.
4. Add a test in `Scripts/Tests/Tcg/suites/`.

Unhandled `effect_type` values log `[INFO]`. Do not silently `pass` unless intentional.

---

## File size and organization

- Target **≤ 400 lines** for new files.
- Use section headers in large files:

```gdscript
# ─── Public entry point ──────────────────────────────────────────────────────
```

- New console commands should eventually live in dedicated handler modules rather than
  growing `GameController.gd` further.

---

## Comments

- One-line file purpose at the top; cite rules doc sections when relevant
  (`# per §8 implementation rules`).
- Explain *why*, not *what*.
- No comments on obvious code.

---

## Testing

```bash
./Scripts/run_tcg_tests.sh
```

- Fixtures set phase/zones explicitly; include channeled `runes` when testing power costs.
- Use `cmd_with_choices()` or `set_choices()` + prompt draining for interactive steps.
- Bug fixes should include a regression test when feasible.

---

## Python (`ai_agent/`, `Scripts/bugs/`)

- `from __future__ import annotations`
- Type hints on public functions
- `pathlib.Path` for file paths
- Module docstrings on entry points
- Secrets via environment variables, never committed

---

## Diff discipline

- Minimize scope — no drive-by refactors in bug-fix PRs.
- Match surrounding style in the area you edit.
- Run `./Scripts/run_tcg_tests.sh` before submitting engine changes.
