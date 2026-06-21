# Riftbound Simulation — Gaps & Implementation Plan

> Analysis of the Godot TCG simulation (`Scripts/Game/`) against card data in `Data/Cards/` and the rules distilled in `riftbound-implementation-rules.md` and `riftbound-card-data-schema.md`.  
> Generated: 2026-05-26. Updated: 2026-06-15.

---

## 1. Purpose

The Godot project implements a **command-console-driven 1v1 Riftbound duel** with two starter decks (`Data/Decks/starter-deck-p1.json`, `starter-deck-p2.json`). Card definitions live in JSON under `Data/Cards/`. The engine resolves abilities through `AbilityResolver.gd` and routes player input through `GameController.gd`.

This document records **what works today**, **what card data expects**, and **what is missing** so future work can be prioritized in dependency order.

---

## 2. Current Card Data Inventory

| File | Count | Notes |
|---|---|---|
| `units.json` | 20 | Fury/Chaos starter units + Calm/Body Master Yi units |
| `spells.json` | 12 | Action, Reaction, Hidden, and Master Yi spells |
| `gear.json` | 1 | Scrapheap (on-play / on-discard / on-death triggers) |
| `battlefields.json` | 4 | Conquer/defend triggers (incl. Fortified Position) |
| `legends.json` | 2 | Jinx — Loose Cannon, Master Yi — Wuju Bladesman |
| `runes.json` | 4 | Fury, Chaos, Calm, Body Runes (tap + recycle activated) |
| `tokens.json` | 0 | Empty — no token definitions yet |

**Starter deck scope:** 24 unique card IDs, 40+ main-deck cards each, 12 runes, 3 battlefields per deck (2 placed at game start).

---

## 3. What the Simulation Already Implements

These systems are present and usable for the starter-deck TCG simulation:

| Area | Status | Key files / notes |
|---|---|---|
| Game setup | ✅ | Deck load, deck validation, legend/champion zones, battlefield selection, 4-card opening hand, mulligan |
| Turn structure | ✅ | Awaken → Beginning triggers/Temporary cleanup → Hold scoring → Channel → Draw → Main → Ending |
| Command console | ✅ | `play`, `move`, `tap`/`recycle rune`, `use`, `react`, `pass`, `end turn`, `hide`, `equip`, `assign`, `choose`, info commands |
| Chain (stack) | ✅ | LIFO resolve, Closed/Open states, reaction window, target prompts |
| Standard movement | ✅ | Base ↔ Battlefield; Ganking BF ↔ BF |
| Combat | ✅ (rules-light) | Showdown pass loop, optional manual attacker assignment, default auto assignment with Tank priority, cleanup/recall |
| Non-combat Showdown | ✅ | Focus passing, control/conquer scoring, Winning Point draw replacement |
| Cleanup | ✅ | Win check, lethal damage, Deathknell hook, uncontrolled battlefields, unattached gear recall, staged combat/showdown prompts |
| Resources | ✅ | Rune pool, tap/recycle, auto-pay on play/ability costs, Hidden hide cost |
| Triggers | ✅ | `TriggerDispatcher.gd` handles `on_play`, `on_discard`, `on_move`, `on_conquer`, `on_defend`, `beginning_phase_start`, delayed end-of-turn `ready_runes`, and passive keyword auras |
| Conditions / targeting | ✅ | `ConditionEvaluator.gd` and `TargetResolver.gd` cover hand size, discard-this-turn, Legion, Might filters, battlefield-local units, trash units, and unit-or-gear targets |
| Keywords (partial) | ✅ | Accelerate, Assault, Shield, Tank, Ganking, Deathknell, Hidden, Temporary, Ambush gate, Deflect surcharge |
| Effect handlers (partial) | ✅ | Current starter-pool handlers are implemented; unused schema effects remain missing (see §4.1) |
| AI integration | ✅ (with caveats) | `BriefStateSerializer`, `LegalMoveEnumerator`, HTTP agent loop; see §4.5 for command-format pitfalls |

---

## 4. Remaining Gaps and Constraints

### 4.1 Unimplemented effect and keyword surface

These effects are still unhandled by `AbilityResolver.gd` and should be treated as unsupported until cards need them:

| `effect_type` | Current status |
|---|---|
| `spend_buff` | No handler |
| `banish` | No handler, though `PlayerState` has a banishment zone |
| `gain_xp` | No handler |
| `prevent_damage` | No handler |
| `custom` | No script-loading path for bespoke card behavior |

Other content-facing gaps:

- `play_token` has a handler, but `Data/Cards/tokens.json` is empty.
- `vision` has no implementation and no current cards.
- `on_attack` is not emitted. `on_defend` is emitted at combat start and is used by Reaver's Row.

### 4.2 Rule fidelity gaps

| Rule / workflow | Current behavior |
|---|---|
| Chosen Champion identity | `DeckLoader` places a champion in `champion_zone`, but deck copies are not specially treated as Chosen Champion copies in other zones |
| Signature card limit | Not enforced by `DeckLoader.validate()` |
| Cemetery Attendant choice | `choose_trash_return` exists, but `return_from_trash` currently returns the last matching trash card without opening that prompt |
| Gear `on_death` | Unit Deathknell hooks run during lethal cleanup; Scrapheap's gear `on_death` ability is not tied to an attached-unit death path |
| Manual combat assignment | Supported only when `gs.auto_combat_damage` is false; defender damage is still auto-assigned |
| Staged combat chaining | Cleanup prompts when multiple battlefields are staged, but `CombatProcessor.finalize_combat()` can still auto-open the next staged combat |

### 4.3 Trigger and targeting architecture

`TriggerDispatcher.emit(event, ctx, gs, controller)` is the central trigger path. Its source scan is intentionally scoped:

- `on_play`: only the played card's abilities.
- `on_discard`: only the discarded card's abilities.
- `on_move`: only the moved card's abilities.
- `beginning_phase_start`: active player's legend.
- `on_conquer` / `on_defend`: matching battlefield abilities plus board/base permanents.

Passive keyword auras are refreshed by `emit_passive_auras()` and currently cover `gain_keywords`. Magma Wurm's "other friendly units enter ready" is an `on_play` effect, not a passive aura refresh.

### 4.4 Cost and payment constraints

- Use `GameController.try_pay_cost()` for costs with energy or power so auto-tap/auto-recycle can satisfy shortfalls.
- Discard costs go through `begin_discard()` to preserve player choice and `on_discard` triggers.
- `play_self` assumes the dispatcher already paid the ability cost; `_play_self()` only moves the card from trash to base.
- `CostCalculator.compute_play_cost()` applies card-local `cost_reduction`, `per_card_in_trash`, Legion conditions, and Accelerate surcharge.

### 4.5 Developer-facing command pitfalls

- `_cmd_help()` lists `play ... from hidden`, but currently omits `hide`, `equip`, `assign`, and `choose`.
- The controller expects `equip <gear-id> target <unit-id>`. `LegalMoveEnumerator` currently emits `equip <gear-id> to <unit-id>`, which is not accepted by `_cmd_equip()`.
- Prompt types in use: `choose_target`, `choose_discard`, `choose_optional`, `choose_battlefield`, `choose_trash_return`.

### 4.6 Tests

The active headless TCG suite is under `Scripts/Tests/Tcg/` and runs with:

```bash
./Scripts/run_tcg_tests.sh
```

Coverage includes setup/deck validation, turn structure, resources/Hidden, movement, chain, combat, cleanup, scoring, showdown, and starter card scenarios. Older `Scripts/Tests/C1BoardStateTests.gd` and `D1CombatResolverTests.gd` target the separate grid-based champion combat prototype, not this command-console TCG engine.

---

## 5. Per-Card Implementation Status

Legend: ✅ works · ⚠️ partial · ❌ broken/missing

### Units

| Card | Status | Gap |
|---|---|---|
| Blazing Scorcher | ✅ | Accelerate works |
| Brazen Buccaneer | ✅ | Optional discard cost reduction at play with player choice |
| Chemtech Enforcer | ✅ | `discard` on play with player-chosen card |
| Flame Chompers | ✅ | `on_discard` → optional `play_self` |
| Magma Wurm | ✅ | `other_friendly_units_enter_ready` readies other friendly units on play |
| Raging Soul | ✅ | Conditional `gain_keywords` applies after a discard this turn |
| Jinx — Demolitionist | ✅ | Accelerate + player-chosen discard on play |
| Vi — Destructive | ✅ | Activated `give_might` pays `cost.recycle: 1` from deck |
| Cemetery Attendant | ⚠️ | `return_from_trash` works but no target choice (returns last unit in trash) |
| Undercover Agent | ✅ | Deathknell `discard_then_draw` with player choice |
| Traveling Merchant | ✅ | `on_move` `discard_then_draw` with player choice |
| Rhasa the Sunderer | ✅ | `cost_reduction` per card in trash applies in `CostCalculator` |

### Spells

| Card | Status | Gap |
|---|---|---|
| Void Seeker | ✅ | Damage + draw on resolution |
| Get Excited! | ✅ | Player-chosen discard cost + variable damage |
| Fight or Flight | ✅ | `move_unit_to_base`; Hidden hide/play-from-hidden workflow covered by resource tests |
| Gust | ✅ | `return_to_hand` with Might ≤ 3 target filter |
| Fading Memories | ✅ | `give_keyword` accepts nested keyword params; Temporary cleanup is implemented |

### Gear, Battlefields, Legend

| Card | Status | Gap |
|---|---|---|
| Scrapheap | ⚠️ | `on_play` and `on_discard` draw work; gear `on_death` still lacks an attached-death hook |
| Zaun Warrens | ✅ | `on_conquer` → `discard_then_draw` |
| Targon's Peak | ✅ | `on_conquer` queues delayed `ready_runes` for end of turn |
| Reaver's Row | ✅ | `on_defend` optional `move_unit_to_base` through battlefield trigger dispatch |
| Jinx — Loose Cannon | ✅ | `beginning_phase_start` draw with hand size condition |

### Runes

| Card | Status |
|---|---|
| Fury Rune / Chaos Rune | ✅ tap + recycle |

---

## 6. Recommended Next Work

Work in this order to close the remaining verified gaps without reworking implemented systems.

### 6.1 Console / AI command alignment

1. Update `_cmd_help()` to list `hide`, `equip`, `assign`, and `choose`.
2. Align `LegalMoveEnumerator` gear commands with `_cmd_equip()` (`equip <gear-id> target <unit-id>`).
3. Add a regression for AI-enumerated equip commands once gear attachment is exercised by the starter decks.

### 6.2 Remaining starter-card fidelity

1. Add a trash-choice prompt for `return_from_trash` so Cemetery Attendant does not auto-pick the last matching unit.
2. Wire Scrapheap's gear `on_death` to an attached-death or gear-destruction path if that rule is intended for the simulation.
3. Add direct coverage for Reaver's Row `on_defend` optional decline/accept behavior.

### 6.3 Future content hooks

1. Implement unsupported effects only when cards need them: `spend_buff`, `banish`, `gain_xp`, `prevent_damage`, and `custom`.
2. Populate `tokens.json` before relying on `play_token`.
3. Add `vision` and `on_attack` dispatch when cards introduce those mechanics.
4. Extend deck validation for signature-card limits and Chosen Champion identity handling.

---

## 7. Relevant File Map

| Area | Primary files |
|---|---|
| Triggers / conditions / targets | `Scripts/Game/TriggerDispatcher.gd`, `ConditionEvaluator.gd`, `TargetResolver.gd` |
| Ability effects / costs | `Scripts/Game/AbilityResolver.gd`, `CostCalculator.gd`, `ChainProcessor.gd` |
| Console workflows / prompts | `Scripts/Game/GameController.gd` |
| Combat / showdown / cleanup | `Scripts/Game/CombatProcessor.gd`, `ShowdownProcessor.gd`, `CleanupProcessor.gd` |
| Deck setup / validation | `Scripts/Data/DeckLoader.gd`, `Data/Decks/*.json` |
| AI command generation | `Scripts/AI/LegalMoveEnumerator.gd`, `BriefStateSerializer.gd`, `AIPlayer.gd` |
| Card data / future content | `Data/Cards/*.json`, optional future `Scripts/Cards/Special/` |
| Regression tests | `Scripts/Tests/Tcg/`, `Scripts/run_tcg_tests.sh` |

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

## 8b. OGS Master Yi (Calm/Body) Deck — Status & Remaining Gaps

A second deck was added (`Data/Decks/master-yi-calm-body.json`, source: `Docs/decklist-2`,
`Docs/cardlist-2.txt`). It introduces the **Calm** and **Body** domains, a Legend with a
combat aura, conditional passive Might, and several new spell effects. It is selectable from
the Main Menu ("Master Yi Deck (vs AI)").

### New content added

| Card | File | Status |
|---|---|---|
| Calm Rune (OGN-042), Body Rune (OGN-126) | `runes.json` | ✅ Full (tap energy / recycle power) |
| Fortified Position (OGN-279) | `battlefields.json` | ✅ `on_defend` grants Shield 2 (give_keyword) |
| Master Yi - Wuju Bladesman (OGS-019) — Legend | `legends.json` | ✅ Aura: +2 Might to a lone defender (`aura_might`) |
| Stalwart Poro (OGN-052), Zephyr Sage (OGS-005) | `units.json` | ✅ Shield keyword |
| Playful Phantom (OGN-049), Mountain Drake (OGN-142) | `units.json` | ✅ Vanilla |
| Master Yi - Honed (OGS-009) | `units.json` | ✅ Ganking + `enter_ready` on play |
| Stormclaw Ursine (OGN-137) | `units.json` | ✅ Tank + channel 1 rune exhausted on play |
| Wielder of Water (OGN-055) | `units.json` | ✅ +2 Might while attacking/defending alone (`conditional_might`) |
| Master Yi - Meditative (OGS-004) | `units.json` | ✅ +4 Might while you have 8+ runes (`conditional_might`) |
| En Garde (OGN-046) | `spells.json` | ✅ `give_might_with_alone_bonus` |
| Mobilize (OGN-134) | `spells.json` | ✅ `channel_rune_or_draw` |
| Confront (OGN-129) | `spells.json` | ✅ `units_enter_ready_this_turn` + draw |
| Cannon Barrage (OGN-127) | `spells.json` | ✅ `deal_damage_all_enemies_in_combat` |
| Meditation (OGN-048) | `spells.json` | ⚠️ Partial — see gaps |
| Gentlemen's Duel (OGS-008) | `spells.json` | ⚠️ Partial — see gaps |
| Highlander (OGS-020) | `spells.json` | ❌ Not implemented — see gaps |

### Engine features added for this deck

- `CardInstance.passive_might_bonus`, recomputed in `TriggerDispatcher.emit_passive_auras`
  (also called after every command in `GameController.submit_command`). Driven by passive
  `conditional_might` (self) and Legend `aura_might` abilities.
- `ConditionEvaluator`: `rune_count_gte`, `while_combat_alone`, `while_defending_alone`.
- `AbilityResolver`: `channel_rune` now honors `exhausted`; new `channel_rune_or_draw`,
  `give_might_with_alone_bonus`, `units_enter_ready_this_turn`,
  `deal_damage_all_enemies_in_combat`.
- `PlayerState.channel_rune(enter_exhausted)`, `PlayerState.units_enter_ready_this_turn`,
  and `_place_unit` honoring that flag.

### Remaining gaps (require further engine work)

1. **Replacement effects (Highlander, OGS-020).** "The next time a friendly unit would die
   this turn, heal/exhaust/recall it instead." The engine has no replacement-effect layer;
   `CleanupProcessor.process_deaths` moves lethally-damaged units straight to Trash. Needs:
   a per-unit/turn "death replacement" registry consulted before a unit dies, plus a recall
   (heal + exhaust + send to base, not a move). The JSON ability is present
   (`effect_type: death_replacement_recall`, `ability_type: replacement`) but logs `[INFO]`.
2. **Optional additional costs (Meditation, OGN-048).** "You may exhaust a friendly unit; if
   you do, draw 2, otherwise draw 1." Costs that prompt the player to choose-and-exhaust a
   unit, with a branching effect, are not supported. Current behavior: draws 1 (the floor);
   the exhaust-for-+1-draw upside is unimplemented (ability `cost.custom = may_exhaust_friendly_unit`).
3. **Multi-target / "fight" effects (Gentlemen's Duel, OGS-008).** The +3 Might half resolves
   (`give_might`), but the second clause — choose an enemy unit, then have the buffed unit and
   that enemy deal damage equal to their Mights to each other — needs (a) carrying a second
   chosen target through resolution and (b) a mutual-damage ("fight") effect. The
   `fight_chosen_units` ability currently logs `[INFO]`.
4. **Two-target resolution generally.** `_play_spell` only sets up one `choose_one` target
   prompt per spell. Cards needing two distinct chosen targets (e.g. Gentlemen's Duel) need a
   target queue on the chain item.

### Battlefields note

`Docs/decklist-2` lists only one battlefield (Fortified Position). A Riftbound deck carries 3,
so `targons-peak` and `reavers-row` were added to round out the deck's `battlefields` list.

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
[x] deal_damage         [x] heal               [x] kill
[x] give_might          [x] give_keyword        [x] buff_unit
[ ] spend_buff          [x] move_unit           [x] stun_unit
[ ] banish              [x] recycle             [x] discard
[x] channel_rune        [x] ready_permanent     [x] play_token
[ ] gain_xp             [x] gain_points         [ ] prevent_damage
[x] cost_reduction      [x] counter_spell       [x] attach
[x] predict             [x] return_to_hand      [x] enter_ready
[~] return_from_trash   [ ] custom

[x] discard_then_draw   [x] move_unit_to_base   [x] play_self
[x] gain_keywords       [x] ready_runes
[x] other_friendly_units_enter_ready
[x] deal_damage_equal_to_discarded_energy_cost

[x] implemented   [~] partial/stub   [ ] missing
```
