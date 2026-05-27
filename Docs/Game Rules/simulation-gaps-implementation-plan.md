# Riftbound Simulation — Gaps & Implementation Plan

> Analysis of the Godot TCG simulation (`Scripts/Game/`) against card data in `Data/Cards/` and the rules distilled in `riftbound-implementation-rules.md` and `riftbound-card-data-schema.md`.  
> Generated: 2026-05-26.

---

## 1. Purpose

The Godot project implements a **command-console-driven 1v1 Riftbound duel** with two starter decks (`Data/Decks/starter-deck-p1.json`, `starter-deck-p2.json`). Card definitions live in JSON under `Data/Cards/`. The engine resolves abilities through `AbilityResolver.gd` and routes player input through `GameController.gd`.

This document records **what works today**, **what card data expects**, and **what is missing** so future work can be prioritized in dependency order.

---

## 2. Current Card Data Inventory

| File | Count | Notes |
|---|---|---|
| `units.json` | 12 | Fury and Chaos units for both starter decks |
| `spells.json` | 5 | Mix of Action, Reaction, and Hidden spells |
| `gear.json` | 1 | Scrapheap (on-play / on-discard / on-death triggers) |
| `battlefields.json` | 3 | Each has a triggered ability on conquer or defend |
| `legends.json` | 1 | Jinx — Loose Cannon (beginning-phase draw) |
| `runes.json` | 2 | Fury Rune, Chaos Rune (tap + recycle activated) |
| `tokens.json` | 0 | Empty — no token definitions yet |

**Starter deck scope:** 24 unique card IDs, 40+ main-deck cards each, 12 runes, 3 battlefields per deck (2 placed at game start).

---

## 3. What the Simulation Already Implements

These systems are present and usable for basic games:

| Area | Status | Key files |
|---|---|---|
| Game setup | ✅ | Deck load, legend/champion zone, battlefield selection, 4-card opening hand, mulligan |
| Turn structure | ✅ (partial) | Awaken → Beginning (Hold scoring) → Channel → Draw → Main → Ending |
| Command console | ✅ | `play`, `move`, `tap`/`recycle rune`, `use`, `react`, `pass`, `end turn`, info commands |
| Chain (stack) | ✅ (basic) | LIFO resolve, Closed/Open states, reaction window, target prompts |
| Standard movement | ✅ | Base ↔ Battlefield; Ganking BF ↔ BF |
| Combat | ✅ (simplified) | Showdown pass loop → auto damage assignment (Tank priority) → cleanup/recall |
| Non-combat Showdown | ✅ (basic) | Focus passing → control/conquer scoring |
| Cleanup | ✅ (partial) | Win check, lethal damage, Deathknell hook, uncontrolled battlefields, staged combat/showdown |
| Resources | ✅ | Rune pool, tap/recycle, auto-pay on play |
| Keywords (partial) | ✅ | Accelerate, Assault, Shield, Tank, Ganking, Deathknell |
| Effect handlers (partial) | ✅ | 22 of ~30 effect types have handlers in `AbilityResolver.gd` |
| AI integration | ✅ | `BriefStateSerializer`, `LegalMoveEnumerator`, HTTP agent loop |

---

## 4. Gap Summary

### 4.1 Effect types used in `Data/` but not implemented

These appear in card JSON and log `[INFO] Unhandled effect type` (or silently fail) at runtime:

| `effect_type` | Used by | Required behavior |
|---|---|---|
| `discard_then_draw` | Undercover Agent, Traveling Merchant, Zaun Warrens | Discard N from hand, then draw N |
| `move_unit_to_base` | Fight or Flight, Reaver's Row | Move chosen (or triggered) unit from battlefield to owner's base |
| `play_self` | Flame Chompers | When discarded, optionally pay cost and play this unit from trash/hand |
| `other_friendly_units_enter_ready` | Magma Wurm | All other friendly units enter Ready (passive aura) |
| `gain_keywords` | Raging Soul | Grant Assault/Ganking while condition is met |
| `ready_runes` | Targon's Peak | Ready N channeled runes (possibly delayed to end of turn) |
| `deal_damage_equal_to_discarded_energy_cost` | Get Excited! | Discard 1, deal damage equal to that card's energy cost |

### 4.2 Effect types in schema/registry but unused or stubbed

| `effect_type` | Status | Notes |
|---|---|---|
| `cost_reduction` | **Stub** | `CostCalculator` only checks `legion` keyword on the card itself; ignores passive abilities (Brazen Buccaneer, Rhasa) and `per_card_in_trash` |
| `move_unit` | **Stub** | Logs only; no zone change |
| `heal` | **Partial** | Always heals all damage; ignores `amount` param |
| `give_keyword` | **Partial** | Expects string `keyword`; Fading Memories passes a nested `{id, value}` object |
| `banish`, `spend_buff`, `gain_xp`, `prevent_damage`, `play_token`, `custom` | **Not used** in current card pool; no handlers or no card scripts |

### 4.3 Trigger / timing system — largest architectural gap

Today, abilities fire only in three places:

| Timing | Where fired |
|---|---|
| `on_play` | `GameController._fire_on_play_triggers()` |
| `resolution` | `ChainProcessor._execute_chain_item()` |
| `on_death` | `CleanupProcessor._process_deaths()` (only if unit has Deathknell keyword) |

**Timings present in card data with no dispatcher:**

| Timing | Cards affected |
|---|---|
| `on_discard` | Flame Chompers, Scrapheap |
| `on_move` | Traveling Merchant |
| `on_conquer` | Zaun Warrens, Targon's Peak |
| `on_defend` | Reaver's Row |
| `beginning_phase_start` | Jinx — Loose Cannon (legend) |

**Recommendation:** Add a `TriggerDispatcher.gd` (or extend `GameController`) that centralizes event emission:

```
emit(event_name, context) → scan all relevant sources (board units, gear, battlefields, legends) → filter by timing + condition → resolve optional/required abilities → cleanup
```

Hook points needed:

- After discard (play costs, Chemtech Enforcer, spell costs)
- After unit zone change (`_cmd_move`, `_place_unit`, combat recall)
- After conquer scoring (`ShowdownProcessor._establish_control`, `CombatProcessor.finalize_combat`)
- At start of Beginning Phase, **before** Hold scoring (Temporary keyword, legend triggers)
- At combat Showdown start (attack/defend triggers — schema lists `on_defend`; Reaver's Row uses it)

### 4.4 Conditions — not evaluated anywhere

| `condition.type` | Used by | Expected rule |
|---|---|---|
| `hand_size_lte` | Jinx legend | Draw if hand size ≤ N at beginning phase |
| `discarded_card_this_turn` | Raging Soul | Gain keywords if controller discarded this turn |
| `might_lte` | Gust (in `effect_params`) | Target filter: only units with Might ≤ 3 |

Also missing from schema but used in data:

- `per_card_in_trash` inside `cost_reduction` effect params (Rhasa the Sunderer)

**Recommendation:** Add `ConditionEvaluator.gd` with `evaluate(condition, source, gs) -> bool` and call it from trigger dispatch and targeting validation.

### 4.5 Keywords — present in data but not enforced

| Keyword | In data? | Engine status |
|---|---|---|
| `action` | Yes (3 spells) | Partial — `is_action` flag checked; Action spells during Showdown need verification |
| `reaction` | Yes (Gust) | ✅ via `react` command |
| `accelerate` | Yes (2 units) | ✅ via `play <id> accelerate` |
| `assault`, `shield`, `tank`, `ganking`, `deathknell` | Yes | ✅ |
| `hidden` | Yes (Fight or Flight) | ❌ No `hide` command; facedown zone exists on `BattlefieldEntry` but unused for placement |
| `temporary` | Yes (via Fading Memories grant) | ❌ No beginning-phase kill |
| `vision` | No cards yet | ❌ Not implemented |
| `legion` | No cards in pool | Logic exists on wrong predicate (`card.has_keyword("legion")` vs ability `condition.type`) |
| `deflect` | No cards in pool | Cost surcharge coded in `CostCalculator` only |
| `ambush` | No cards in pool | Explicitly deferred — units forced to base on play |
| `equip` | No cards in pool | ❌ Gear attach via `use` skips `attach` abilities |

### 4.6 Core rules — simplified or missing

| Rule | Spec (impl rules §) | Current behavior |
|---|---|---|
| Conquer + Winning Point | §13 | ❌ Conquer always awards 1 point; no "must have scored every battlefield this turn" check |
| Domain identity | §1 | ❌ Deck loader does not validate cards against legend domains |
| Deck construction limits | §1 | ❌ No validation (40 cards, 12 runes, 3-of limit, signature cap) |
| Beginning Step before Scoring | §6 | ❌ Legend/Temporary triggers should fire before Hold; Hold runs immediately |
| Temporary cleanup | §15 | ❌ Units with Temporary not killed at beginning phase |
| Burn Out | §13 | ✅ Partial — shuffle trash, opponent +1 point on draw from empty deck |
| Manual combat damage assignment | §12, §19 | ❌ Auto-assigned only; `assign` command is a no-op stub |
| Turn player picks staged combat | §17 step 8 | ❌ Auto-starts first staged combat/showdown |
| Attack / Defend triggers | §12 | ❌ Not fired at combat Showdown start |
| Optional abilities | schema `is_optional` | ❌ Always auto-resolves (e.g. Brazen Buccaneer discount, Reaver's Row defend) |
| Ability costs on resolution | schema `cost.discard` | ❌ Get Excited! discard cost not paid; Brazen Buccaneer optional discard ignored |
| Vi recycle cost | `cost.recycle: 1` | ❌ `CostCalculator.pay_cost` handles `recycle_self` (runes) only, not recycle-from-deck/trash |
| Gear recall from battlefield | §4 | Partial — cleanup stub iterates gear but does not recall unattached gear at BF |
| Zone-change reset | §3 | Partial — trash clears stats; hand return clears temps; not all paths covered |
| Banishment zone | §3, §18 | Zone exists in `PlayerState` but no `banish` effect or command |
| Second player +1 rune | §2 | Buggy heuristic — uses `turn_number <= 2 and channeled_runes.is_empty()` instead of tracking second player's first channel |
| Chosen Champion identity | §1 | ❌ Copies in deck/hand/trash not treated as Chosen Champion |
| Signature card limit | §1 | ❌ Not enforced |
| Battlefield abilities as sources | §4 | ❌ Battlefield `CardDefinition.abilities` never scanned by trigger system |
| Legend zone abilities | §4 | ❌ Legend never scanned for triggers |

### 4.7 Commands missing from console

| Command | Needed for |
|---|---|
| `hide <id> at <battlefield>` | Hidden keyword |
| `equip <gear-id> target <unit-id>` or `use` on attach abilities | Gear attachment |
| `assign <n> to <id>` / `assign done` | Manual combat damage (rules-accurate mode) |
| `choose` improvements | Target filtering (Gust might ≤ 3), optional declines, recycle-from-deck choices |

### 4.8 Targeting gaps

Card data uses target strings not handled by `_build_target_prompt` / validation:

| Target string | Cards |
|---|---|
| `friendly_unit_here` | Reaver's Row |
| `unit_or_gear_at_battlefield` | Fading Memories |
| `unit` (return from trash filter) | Cemetery Attendant |

**Recommendation:** Add `TargetResolver.gd` to enumerate legal targets per filter and validate `choose` responses.

### 4.9 Tests and legacy code

`Scripts/Tests/C1BoardStateTests.gd` and `D1CombatResolverTests.gd` target a **grid-based champion combat system** (`ChampionInstance`, `GridSpec`, `CombatResolver`) that is separate from the TCG simulation described above. They do not validate `GameController`, `CombatProcessor`, or card ability resolution.

**Recommendation:** Add headless tests for the TCG engine (mulligan, Hold scoring, chain resolve, Deathknell, conquer scoring) under a new `Scripts/Tests/Tcg/` folder.

---

## 5. Per-Card Implementation Status

Legend: ✅ works · ⚠️ partial · ❌ broken/missing

### Units

| Card | Status | Gap |
|---|---|---|
| Blazing Scorcher | ✅ | Accelerate works |
| Brazen Buccaneer | ❌ | Optional discard cost reduction not applied at play |
| Chemtech Enforcer | ⚠️ | `discard` on play works but discards arbitrary first card, no choice |
| Flame Chompers | ❌ | `on_discard` → `play_self` not implemented |
| Magma Wurm | ❌ | Passive `other_friendly_units_enter_ready` not applied |
| Raging Soul | ❌ | Conditional `gain_keywords` not evaluated |
| Jinx — Demolitionist | ⚠️ | Accelerate + discard on play work; discard not player-chosen |
| Vi — Destructive | ❌ | Activated `give_might` works but `cost.recycle: 1` not paid |
| Cemetery Attendant | ⚠️ | `return_from_trash` works but no target choice (returns last unit in trash) |
| Undercover Agent | ❌ | Deathknell fires but `discard_then_draw` effect missing |
| Traveling Merchant | ❌ | `on_move` trigger not fired |
| Rhasa the Sunderer | ❌ | `cost_reduction` per card in trash not applied |

### Spells

| Card | Status | Gap |
|---|---|---|
| Void Seeker | ✅ | Damage + draw on resolution |
| Get Excited! | ❌ | Discard cost + variable damage effect missing |
| Fight or Flight | ❌ | `move_unit_to_base` not implemented; Hidden not placeable |
| Gust | ⚠️ | `return_to_hand` works; Might ≤ 3 filter not enforced |
| Fading Memories | ⚠️ | `give_keyword` param shape mismatch; Temporary not enforced after grant |

### Gear, Battlefields, Legend

| Card | Status | Gap |
|---|---|---|
| Scrapheap | ⚠️ | `on_play` draw works; `on_discard` and `on_death` not fired |
| Zaun Warrens | ❌ | `on_conquer` → `discard_then_draw` |
| Targon's Peak | ❌ | `on_conquer` → `ready_runes` (delayed) |
| Reaver's Row | ❌ | `on_defend` optional `move_unit_to_base` |
| Jinx — Loose Cannon | ❌ | `beginning_phase_start` draw with hand size condition |

### Runes

| Card | Status |
|---|---|
| Fury Rune / Chaos Rune | ✅ tap + recycle |

---

## 6. Recommended Implementation Phases

Work in this order to unblock the most cards with the least rework.

### Phase A — Trigger infrastructure (blocks 10+ cards)

1. Create `TriggerDispatcher.gd` with event types: `on_discard`, `on_move`, `on_conquer`, `on_defend`, `beginning_phase_start`, `on_attack`, `on_defend_combat`.
2. Create `ConditionEvaluator.gd`.
3. Wire hooks in `GameController`, `CleanupProcessor`, `ShowdownProcessor`, `CombatProcessor`, and `_execute_start_of_turn`.
4. Track `discarded_this_turn` on `PlayerState`.
5. Scan **battlefields** and **legends** as ability sources, not only units/gear.

**Unlocks:** Scrapheap (partial), Flame Chompers, Traveling Merchant, all battlefield abilities, Jinx legend.

### Phase B — Missing effect handlers (blocks 7 effect types)

Implement in `AbilityResolver.gd`:

1. `discard_then_draw`
2. `move_unit_to_base`
3. `ready_runes`
4. `gain_keywords` (runtime keyword grant while condition holds)
5. `other_friendly_units_enter_ready`
6. `deal_damage_equal_to_discarded_energy_cost`
7. `play_self`

Fix existing handlers:

- `give_keyword` — accept both string and `{id, value}` forms
- `cost_reduction` — read passive abilities + `per_card_in_trash`
- `return_from_trash` — player choice from filtered trash

**Unlocks:** Get Excited!, Fight or Flight, Undercover Agent, Magma Wurm, Raging Soul, Targon's Peak, Reaver's Row, Zaun Warrens, Brazen Buccaneer, Rhasa.

### Phase C — Costs, choices, and targeting

1. Extend `CostCalculator.pay_cost` for `discard`, `recycle` (non-self), `kill_friendly`.
2. Prompt flow for optional abilities (`is_optional`) and discard-for-cost (Get Excited!, Brazen Buccaneer).
3. Player choice for discard targets and trash-return targets.
4. `TargetResolver` for Gust (`might_lte`), Fading Memories (`unit_or_gear_at_battlefield`).

**Unlocks:** Correct interactive play for half the spell pool and several units.

### Phase D — Keywords and commands

1. **Hidden:** `hide` command, facedown placement, free reaction play next turn.
2. **Temporary:** kill at beginning phase before Hold.
3. **Vision:** on-play scry + optional recycle (when cards added).
4. **Ambush:** allow `play <unit> to battlefield-*` when unit has Ambush.
5. **Equip/attach:** route gear `attach` activated abilities through `use`.
6. Fix **Legion** to use ability `condition.type == "legion"`, not card keyword.

### Phase E — Rules fidelity

1. Conquer + Winning Point rule.
2. Fix second-player first-channel +1 rune tracking.
3. Beginning Step ordering (triggers → then Hold scoring).
4. Manual combat damage assignment (optional `--auto-combat` flag for AI).
5. Turn player chooses which staged showdown/combat to resolve.
6. Domain identity + deck validation in `DeckLoader`.
7. Gear recall cleanup at battlefields.

### Phase F — Content and tooling

1. Populate `tokens.json` if token cards are added to decks.
2. Add `custom` effect script loading (`res://Scripts/Cards/Special/<id>.gd`) for effects that don't fit the registry.
3. TCG engine headless tests.
4. Expand `LegalMoveEnumerator` for `hide`, equip, and prompted choices.

---

## 7. File Touch List (by phase)

| Phase | Primary files |
|---|---|
| A | New: `TriggerDispatcher.gd`, `ConditionEvaluator.gd` · Edit: `GameController.gd`, `PlayerState.gd`, `ShowdownProcessor.gd`, `CombatProcessor.gd`, `CleanupProcessor.gd` |
| B | `AbilityResolver.gd`, `CostCalculator.gd` |
| C | `GameController.gd` (`_cmd_choose`, pending prompts), `ChainProcessor.gd`, new `TargetResolver.gd` |
| D | `GameController.gd` (new commands), `TurnStateMachine.gd`, `LegalMoveEnumerator.gd` |
| E | `DeckLoader.gd`, `CombatProcessor.gd`, `CleanupProcessor.gd`, `ShowdownProcessor.gd` |
| F | `Data/Cards/tokens.json`, `Scripts/Tests/Tcg/`, `Scripts/Cards/Special/` |

---

## 8. Success Criteria

The starter-deck simulation can be considered **feature-complete for the current card pool** when:

1. Every ability in `Data/Cards/*.json` resolves correctly in a manual test game.
2. All keyword-bearing cards in the pool behave per `riftbound-implementation-rules.md` §15.
3. Legend and battlefield abilities fire on the correct timing.
4. Optional costs and targets prompt the active player (human or AI via `choose`).
5. Hold, Conquer, Burn Out, and Winning Point scoring match §13.
6. `LegalMoveEnumerator` lists only genuinely legal commands for each decision point.

---

## 9. Related Documents

| Document | Role |
|---|---|
| `riftbound-implementation-rules.md` | Authoritative rules subset for engine behavior |
| `riftbound-card-data-schema.md` | JSON schema, effect registry, keyword reference |
| `ai-agent-implementation-plan.md` | Python agent contract; §13.1 notes Ambush deferral |
| `Docs/cards.txt` | Human-readable card text reference |
| `Docs/decklist-1` | Source decklist for starter decks |

---

## 10. Quick Reference — Effect Handler Checklist

```
[x] add_energy          [x] add_power           [x] draw
[x] deal_damage         [~] heal               [x] kill
[x] give_might          [~] give_keyword        [x] buff_unit
[ ] spend_buff          [~] move_unit           [x] stun_unit
[ ] banish              [x] recycle             [x] discard
[x] channel_rune        [x] ready_permanent     [x] play_token
[ ] gain_xp             [x] gain_points         [ ] prevent_damage
[~] cost_reduction      [x] counter_spell       [x] attach
[x] predict             [x] return_to_hand      [x] enter_ready
[x] return_from_trash   [ ] custom

[ ] discard_then_draw   [ ] move_unit_to_base   [ ] play_self
[ ] gain_keywords       [ ] ready_runes
[ ] other_friendly_units_enter_ready
[ ] deal_damage_equal_to_discarded_energy_cost

[x] implemented   [~] partial/stub   [ ] missing
```
