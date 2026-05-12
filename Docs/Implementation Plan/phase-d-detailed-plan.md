# Phase D — Deterministic Turn-Based Autobattle

## Overview

Replace `RunController.stub_resolve_combat()` with a real combat engine.
Given a `PlanningSnapshot` (two locked boards), produce a reproducible
`CombatOutcome` and a replayable event log, then drive a step-by-step
visual replay on the board during `COMBAT_RESOLVE`.

No abilities, no item stat bonuses, no randomness.

---

## Combat rules locked for Phase D

| Rule | Value |
|------|-------|
| Turn order | Sort all alive units by `speed` DESC; ties broken by `instance_id` ASC |
| Action per turn | If any enemy is within attack range → **ATTACK**; else → **MOVE** one cell toward nearest enemy |
| Attack range | Chebyshev distance ≤ 1 (8 surrounding cells; all units are melee) |
| Nearest enemy | Chebyshev distance to each alive enemy; ties broken by `instance_id` ASC |
| Attack damage | `max(1, attacker.attack − defender.defense)` |
| Death | When `current_health ≤ 0`; unit removed from board immediately and skipped in remaining turns |
| Move step | One cell per turn; pick the empty adjacent cell (Chebyshev 1) that minimises distance to the nearest enemy; if multiple tie, pick lowest `to_key()` lexicographically |
| Blocked movement | If all adjacent cells are occupied or out of bounds, unit stays put |
| Combat end | One side reaches 0 alive units |
| Timeout | 200 ticks (full passes through the sorted list count as 1 tick); if neither side is eliminated, the player loses |
| Item effects | Deferred to Phase F — equipped items grant **no stat bonuses** in Phase D |
| Player / opponent identity | Player champions occupy rows `[rows_per_side, total_rows)`; opponents occupy rows `[0, rows_per_side)` |

---

## Missing resources before implementation

### Scripts (must be created)

| Path | Purpose |
|------|---------|
| `Scripts/Combat/CombatUnit.gd` | Source-agnostic runtime unit; **flat stats** (attack, defense, speed, health) copied from the source at creation time; `SourceKind` enum (`CHAMPION`, `ALLY_CARD`, `SUMMON`) + `source_id` for attribution; combat resolver never branches on source type (see design note below) |
| `Scripts/Combat/CombatBoard.gd` | Mutable grid for combat; `occupancy: Dictionary` (key → CombatUnit), adjacency helpers, move/attack helpers |
| `Scripts/Combat/CombatEvent.gd` | Single timestamped log entry; records action type, acting unit id, target cell/unit, damage dealt, new health, death flag |
| `Scripts/Combat/CombatResolver.gd` | Pure `static` class; `resolve(snapshot, spec) → CombatResult`; no Node, no signals, fully headless-testable |
| `Scripts/Combat/CombatResult.gd` | Return value of the resolver: `player_won`, `player_survivors`, `opponent_survivors`, `events: Array[CombatEvent]` |
| `Scripts/UI/Combat/CombatBoardView.gd` | Scene controller that replays a `CombatResult` event log step-by-step over a grid that mirrors `PlanningBoardView` |
| `Scripts/Tests/D1CombatResolverTests.gd` | Headless unit tests for the resolver |

#### Design note — why `CombatUnit` does not wrap `ChampionInstance`

Ally cards (`CardInstance`) and ability summons have no `ChampionInstance` to wrap.
If `CombatUnit` held `var source: ChampionInstance`, adding those unit types would require
union fields or type-branching inside the resolver.

Instead, all combat-relevant stats are **copied once** from the source when the unit is
built; the resolver then operates on a uniform `CombatUnit` regardless of origin.
The `source_kind` + `source_id` fields carry just enough identity for the event log and
UI replay without leaking domain types into the combat layer.

```
CombatUnit
├── instance_id    : int          # unique within this combat
├── source_kind    : SourceKind   # CHAMPION | ALLY_CARD | SUMMON
├── source_id      : int          # instance_id of originating ChampionInstance / CardInstance
├── display_name   : String       # for event log / UI tokens
├── is_player_side : bool
├── cell           : GridCoord    # mutable during combat
├── max_health     : int          # copied at creation, never written back
├── current_health : int
├── attack         : int
├── defense        : int
└── speed          : int

static from_champion(inst: ChampionInstance, player_side: bool, combat_id: int) → CombatUnit
static from_ally_card(inst: CardInstance, cell: GridCoord, player_side: bool, combat_id: int) → CombatUnit
  └── (Phase D: stats stubbed at 0; wired fully in post-D ally phase)
```

`CombatBoard.from_snapshot()` calls `from_champion()` for all champions in Phase D.
When `PlanningSnapshot.deployed_allies` is non-empty (future phase), it calls
`from_ally_card()` without any change to the resolver.

### Scenes (must be created)

| Path | Purpose |
|------|---------|
| `Scenes/UI/Combat/combat_board_view.tscn` | Node tree for `CombatBoardView`; shares cell size and grid spec with the planning board |
| `Scenes/Tests/d1_tests.tscn` | Headless test runner for D1 resolver tests |

### Scripts (must be modified)

| Path | Change |
|------|--------|
| `Scripts/Run/CombatOutcome.gd` | Add `player_survivor_count`, `opponent_survivor_count`, `combat_result: CombatResult` so `RunRoundDamage` can use real survivor data |
| `Scripts/Run/RunController.gd` | Replace `stub_resolve_combat()` body with a call to `CombatResolver.resolve()`; wire `CombatBoardView` for replay |
| `Scripts/Run/RunShell.gd` | Show `CombatBoardView` during `COMBAT_RESOLVE`; hide it after `request_apply_round_result` |
| `Scenes/Run/run_shell.tscn` | Add `CombatBoardView` node to the scene tree |

### Resources / data (must exist at test time)

| Resource | Requirement |
|----------|-------------|
| `Resources/Domain/DefaultCombatStats.tres` | At least one `ChampionData` must have non-zero `attack`, `defense`, `speed`, and `max_health` for tests to be meaningful |

### Design values locked for D (no longer TBD)

- `CombatStats.attack_range` is **implicit = 1** (Chebyshev); no new field needed in D.
- `RunRoundDamage`: switch `use_flat_damage` to `false` so survivor count drives damage.

---

## Milestones

### D1 — Combat domain layer (pure, no UI)

Create the five new combat scripts. No Node, no signals, no scene dependencies.

**`CombatUnit.gd`**
```gdscript
extends RefCounted
class_name CombatUnit

enum SourceKind { CHAMPION, ALLY_CARD, SUMMON }

# Identity / attribution (used by event log and UI replay only)
var instance_id: int
var source_kind: SourceKind
var source_id: int        # instance_id of originating ChampionInstance / CardInstance
var display_name: String

# Placement
var is_player_side: bool
var cell: GridCoord       # mutable position during combat

# Combat stats — copied from source at creation; never referenced back
var max_health: int
var current_health: int
var attack: int
var defense: int
var speed: int

func is_alive() -> bool: return current_health > 0

static func from_champion(inst: ChampionInstance, player_side: bool, combat_id: int) -> CombatUnit
static func from_ally_card(inst: CardInstance, p_cell: GridCoord, player_side: bool, combat_id: int) -> CombatUnit
```

**`CombatBoard.gd`**
```gdscript
extends RefCounted
class_name CombatBoard

# key → CombatUnit
var occupancy: Dictionary = {}

static func from_snapshot(snapshot: PlanningSnapshot) -> CombatBoard
func unit_at(coord: GridCoord) -> CombatUnit          # null if empty
func place(unit: CombatUnit, coord: GridCoord) -> void
func remove(unit: CombatUnit) -> void
func move(unit: CombatUnit, to: GridCoord) -> void
func alive_units() -> Array[CombatUnit]
func alive_players() -> Array[CombatUnit]
func alive_opponents() -> Array[CombatUnit]
# Returns the 8 Chebyshev-adjacent coords that are in-bounds and empty
func empty_neighbours(coord: GridCoord, spec: GridSpec) -> Array[GridCoord]
# Chebyshev distance between two GridCoords
static func chebyshev(a: GridCoord, b: GridCoord) -> int
```

**`CombatEvent.gd`**
```gdscript
extends RefCounted
class_name CombatEvent

enum Kind { MOVE, ATTACK, DEATH, COMBAT_START, COMBAT_END }

var tick: int
var kind: Kind
var actor_id: int
var actor_cell: GridCoord      # cell after action
var target_id: int             # -1 for MOVE/COMBAT_START/END
var target_cell: GridCoord     # destination for MOVE; defender cell for ATTACK
var damage: int                # 0 for non-ATTACK
var target_health_after: int   # remaining health after hit; -1 for non-ATTACK
var died: bool                 # true if the target died from this hit
```

**`CombatResult.gd`**
```gdscript
extends RefCounted
class_name CombatResult

var player_won: bool
var player_survivors: int
var opponent_survivors: int
var events: Array[CombatEvent] = []
var timed_out: bool = false
```

**`CombatResolver.gd`** (algorithm)

Key method:
```gdscript
static func resolve(snapshot: PlanningSnapshot, spec: GridSpec) -> CombatResult:
    var board := CombatBoard.from_snapshot(snapshot)
    var result := CombatResult.new()
    result.events.append(_make_event(CombatEvent.Kind.COMBAT_START, 0))

    var tick := 0
    while board.alive_players().size() > 0 and board.alive_opponents().size() > 0:
        if tick >= MAX_TICKS:
            result.timed_out = true
            break
        var turn_order := _build_turn_order(board)
        for unit in turn_order:
            if not unit.is_alive():
                continue
            _act(unit, board, spec, result.events, tick)
        tick += 1

    result.player_won = board.alive_opponents().size() == 0 and not result.timed_out
    result.player_survivors = board.alive_players().size()
    result.opponent_survivors = board.alive_opponents().size()
    result.events.append(_make_end_event(result, tick))
    return result
```

Internal helpers:
- `_build_turn_order(board) → Array[CombatUnit]` — sorted by speed DESC, instance_id ASC
- `_act(unit, board, spec, events, tick)` — find nearest enemy; attack if adjacent, else move
- `_nearest_enemy(unit, board) → CombatUnit` — Chebyshev distance, tie by instance_id
- `_best_move(unit, target, board, spec) → GridCoord` — adjacent empty cell minimising distance
- `_do_attack(attacker, defender, board, events, tick)` — apply damage, record event, remove if dead
- `_do_move(unit, to, board, events, tick)` — update position, record event

---

### D2 — Tests (`D1CombatResolverTests.gd`)

Headless; run with `--scene res://Scenes/Tests/d1_tests.tscn`.

Required test cases:

| # | Scenario | Expected |
|---|----------|----------|
| 1 | 1v1: equal stats, attacker reaches defender in one move | combat ends in ≤ 3 ticks |
| 2 | 1v1: attacker already adjacent | attack fires on tick 0 |
| 3 | Attacker kills defender | player wins, 1 survivor |
| 4 | 1v1: defender survives one hit | health reduced by `max(1, atk−def)` |
| 5 | High-defense unit receives minimum 1 damage | damage ≥ 1 always |
| 6 | Faster unit acts first in same tick | turn order by speed |
| 7 | Dead unit skipped in subsequent ticks | no events for dead unit |
| 8 | 2v1: player wins, 1 survivor | correct survivor count |
| 9 | 1v2: player loses | `player_won = false`, `opponent_survivors = 2 - killed` |
| 10 | Timeout (infinite loop guard) | `timed_out = true`, `player_won = false` |
| 11 | Movement blocked by occupied cells | unit stays put event logged |
| 12 | Event log is non-empty after combat | at least COMBAT_START + COMBAT_END |

---

### D3 — Wire resolver into RunController

Replace the stub:
```gdscript
# RunController.gd
func _resolve_combat() -> CombatOutcome:
    if _last_snapshot == null:
        return stub_resolve_combat()   # fallback if no snapshot
    var spec: GridSpec = planning_controller.grid_spec if planning_controller else GridSpec.default_square_5x3_two_sided()
    var result: CombatResult = CombatResolver.resolve(_last_snapshot, spec)
    var outcome := CombatOutcome.new()
    outcome.player_won_round = result.player_won
    outcome.enemy_survivor_count = result.opponent_survivors
    outcome.player_survivor_count = result.player_survivors
    outcome.combat_result = result
    return outcome
```

Call `_resolve_combat()` in `request_resolve_combat_stub()` (rename to `request_resolve_combat()`).
Keep the old stub method as a private fallback so existing tests still pass.

Update `RunRoundDamage.damage_on_loss()` to use `outcome.enemy_survivor_count` (already exists).

---

### D4 — Combat visual replay (`CombatBoardView`)

A read-only visual replay controller that consumes a `CombatResult.events` list and
animates each event on the grid.

**Node structure:**

```
CombatBoardView (Control, new script)
└─ (cell buttons built at runtime — same logic as PlanningBoardView._build_grid)
   (unit tokens: ChampionUI nodes, same as PlanningBoardView board tokens)
```

**Script API:**
```gdscript
class_name CombatBoardView

## Called by RunShell when entering COMBAT_RESOLVE.
func start_replay(result: CombatResult, snapshot: PlanningSnapshot, spec: GridSpec) -> void

## Emitted when the last event has been displayed.
signal replay_finished
```

**Replay loop (coroutine):**
```gdscript
func _run_replay(result: CombatResult) -> void:
    for event in result.events:
        _apply_event(event)
        await get_tree().create_timer(step_delay).timeout
    replay_finished.emit()
```

`_apply_event` moves/removes `ChampionUI` tokens to match each event's `actor_cell`,
flashes a hit indicator for `ATTACK` events, and removes tokens for `DEATH` events.

**`RunShell` changes:**
- On `COMBAT_RESOLVE`: hide `PlanningBoardView`, show `CombatBoardView`, call `start_replay`.
- Connect `CombatBoardView.replay_finished` → auto-enable the "Apply Result" button.
- On `ROUND_RESULT` / `PLANNING`: hide `CombatBoardView`, show `PlanningBoardView`.

**`run_shell.tscn` changes:**
- Add `CombatBoardView` node as a sibling of `PlanningBoardView` inside `PlanningSection`.

---

## File checklist

```
Scripts/Combat/
  CombatUnit.gd          ← NEW (D1)
  CombatBoard.gd         ← NEW (D1)
  CombatEvent.gd         ← NEW (D1)
  CombatResult.gd        ← NEW (D1)
  CombatResolver.gd      ← NEW (D1)

Scripts/UI/Combat/
  CombatBoardView.gd     ← NEW (D4)

Scripts/Tests/
  D1CombatResolverTests.gd ← NEW (D2)

Scenes/UI/Combat/
  combat_board_view.tscn ← NEW (D4)

Scenes/Tests/
  d1_tests.tscn          ← NEW (D2)

Scripts/Run/
  CombatOutcome.gd       ← MODIFY: add player_survivor_count, combat_result
  RunController.gd       ← MODIFY: replace stub, rename method, wire CombatBoardView

Scripts/UI/
  RunShell.gd (Run/)     ← MODIFY: phase-aware view switching
Scenes/Run/
  run_shell.tscn         ← MODIFY: add CombatBoardView node
```

---

## Dependencies on earlier phases

| Dependency | Required for |
|------------|-------------|
| `PlanningSnapshot` (C) | D1: resolver input |
| `GridSpec` / `GridCoord` (C) | D1: adjacency + movement |
| `ChampionInstance` / `CombatStats` (C) | D1: unit stats |
| `CombatOutcome` (B) | D3: outcome consumed by RunController |
| `RunController._phase` state machine (B) | D3: wiring |
| `PlanningBoardView._build_grid` pattern (C) | D4: reused for CombatBoardView |
| `ChampionUI` drag-and-drop widget | D4: reused as combat tokens |

---

## What is explicitly deferred to later phases

| Feature | Phase |
|---------|-------|
| Item stat bonuses in combat | F |
| Champion abilities / color synergies | E or post-F |
| Ally card units on the grid | post-D |
| Attack animations / particles | H |
| Replay scrubbing / pause | H |
| Replay persistence / export | H |
| Ranged attack range > 1 | post-D (requires `CombatStats.attack_range` field) |
