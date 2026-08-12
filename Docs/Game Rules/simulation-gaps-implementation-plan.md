# Riftbound Simulation — Gaps & Implementation Plan

> Analysis of the Godot TCG simulation (`Scripts/Game/`) against card data in `Data/Cards/` and the rules distilled in `riftbound-implementation-rules.md` and `riftbound-card-data-schema.md`.  
> Generated: 2026-05-26. Updated: 2026-08-10.

---

## 1. Purpose

The Godot project implements a **command-console-driven 1v1 Riftbound duel** with two starter decks (`Data/Decks/starter-deck-p1.json`, `starter-deck-p2.json`). Card definitions live in JSON under `Data/Cards/`. The engine resolves abilities through `AbilityResolver.gd` and routes player input through `GameController.gd`.

This document records **what works today**, **what card data expects**, and **what is missing** so future work can be prioritized in dependency order.

---

## 2. Current Card Data Inventory

| File | Count | Notes |
|---|---|---|
| `units.json` | 36 | Fury/Chaos starter units, Calm/Body Master Yi units, and WIP Kai'Sa/Fury/Mind content |
| `spells.json` | 24 | Action, Reaction, Hidden, Master Yi, and WIP Kai'Sa/Fury/Mind spells |
| `gear.json` | 2 | Scrapheap draw hooks and Zhonya's Hourglass death-replacement sacrifice |
| `battlefields.json` | 7 | Conquer/defend triggers and battlefield keywords such as `no_move_to_base` |
| `legends.json` | 3 | Jinx — Loose Cannon, Master Yi — Wuju Bladesman, plus WIP legend data |
| `runes.json` | 5 | Fury, Chaos, Calm, Body, and Mind Runes (tap + recycle activated) |
| `tokens.json` | 1 | `sprite-3m` Temporary unit token for Sprite Mother |

**Configured deck scope:** starter decks for both players, `master-yi-calm-body`, `master-yi-shanghai-open`, and `kaisa-fury-mind-wip`; decks still use 12 runes and 3 battlefields, with 2 battlefields placed at game start.

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
| Effect handlers (partial) | ✅ | Current starter-pool and Master Yi handlers are implemented; unused schema effects remain missing (see §4.1) |
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
| `custom` | No general script-loading path for bespoke card behavior; specific custom costs may be hard-coded in controller/chain paths |

Other content-facing gaps:

- `play_token` has a handler and `sprite-3m` data exists; new token-creating cards still need matching entries in `Data/Cards/tokens.json`.
- `vision` has no implementation and no current cards.
- `on_attack` is not emitted. `on_defend` is emitted at combat start and is used by Reaver's Row.
- `prevent_damage` is implemented only for spell/ability damage prevention this turn (`source: "spells_and_abilities"` or `"all"`). Other damage sources would need new resolver coverage.

### 4.2 Rule fidelity gaps

| Rule / workflow | Current behavior |
|---|---|
| Chosen Champion identity | `DeckLoader` places a champion in `champion_zone`, but deck copies are not specially treated as Chosen Champion copies in other zones |
| Signature card limit | Not enforced by `DeckLoader.validate()` |
| Gear `on_death` | Unit Deathknell hooks run during lethal cleanup; Scrapheap's gear `on_death` ability is not tied to an attached-unit death path |
| Manual combat assignment | Supported only when `gs.auto_combat_damage` is false; defender damage is still auto-assigned |
| Staged combat chaining | Cleanup prompts when multiple battlefields are staged, but `CombatProcessor.finalize_combat()` can still auto-open the next staged combat |
| Mandatory triggered target choice | Optional triggered abilities can prompt for target choice after `choose yes`; mandatory triggered abilities still auto-resolve the first valid target |

### 4.3 Trigger and targeting architecture

`TriggerDispatcher.emit(event, ctx, gs, controller)` is the central trigger path. Its source scan is intentionally scoped:

- `on_play`: only the played card's abilities.
- `on_discard`: only the discarded card's abilities.
- `on_move`: only the moved card's abilities.
- `beginning_phase_start`: active player's legend.
- `on_conquer` / `on_defend`: matching battlefield abilities plus board/base permanents.

Passive keyword and Might auras are refreshed by `emit_passive_auras()` and currently cover `gain_keywords`, `conditional_might`, and legend `aura_might`. Magma Wurm's "other friendly units enter ready" is an `on_play` effect, not a passive aura refresh.

### 4.4 Cost and payment constraints

- Use `GameController.try_pay_cost()` for costs with energy or power so auto-tap/auto-recycle can satisfy shortfalls.
- Discard costs go through `begin_discard()` to preserve player choice and `on_discard` triggers.
- `play_self` assumes the dispatcher already paid the ability cost; `_play_self()` only moves the card from trash to base.
- `CostCalculator.compute_play_cost()` applies card-local `cost_reduction`, `per_card_in_trash`, ability conditions such as Legion, and Accelerate surcharge.
- Legion discounts are represented only as `cost_reduction` abilities with `condition.type = "legion"`; there is no second keyword-based discount pass. This keeps Noxus Hopeful at 4 → 2 energy after another card has been played.
- Meditation's `cost.custom = may_exhaust_friendly_unit` is a hard-coded chain/controller continuation, not a general custom-cost plug-in system.

### 4.5 Developer-facing command pitfalls

- `_cmd_help()` lists `play ... from hidden`, but currently omits `hide`, `equip`, `assign`, and `choose`.
- The controller expects `equip <gear-id> target <unit-id>`. `LegalMoveEnumerator` currently emits `equip <gear-id> to <unit-id>`, which is not accepted by `_cmd_equip()`.
- Prompt types in use: `choose_target`, `choose_discard`, `choose_optional`, `choose_battlefield`, `choose_trash_return`, and `choose_mode`.
- `choose_battlefield` is used both for staged combat/showdown selection and for spell-driven movement destinations (`move_destination_resume`, e.g. Charm). `choose_mode` currently resumes Qiyana's draw-or-channel choice.

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
| Cemetery Attendant | ✅ | `return_from_trash` prompts with `choose_trash_return` when multiple unit cards are in trash |
| Undercover Agent | ✅ | Deathknell `discard_then_draw` with player choice |
| Traveling Merchant | ✅ | `on_move` `discard_then_draw` with player choice |
| Rhasa the Sunderer | ✅ | `cost_reduction` per card in trash applies in `CostCalculator` |
| Noxus Hopeful | ✅ | Legion discount applies once through conditional `cost_reduction` (4 → 2 energy) |
| Qiyana — Victorious | ✅ | `on_conquer` prompts `choose_mode` to draw 1 or channel 1 rune exhausted |

### Spells

| Card | Status | Gap |
|---|---|---|
| Void Seeker | ✅ | Damage + draw on resolution |
| Get Excited! | ✅ | Player-chosen discard cost + variable damage |
| Fight or Flight | ✅ | `move_unit_to_base`; Hidden hide/play-from-hidden workflow covered by resource tests |
| Gust | ✅ | `return_to_hand` with Might ≤ 3 target filter |
| Fading Memories | ✅ | `give_keyword` accepts nested keyword params; Temporary cleanup is implemented |
| Falling Star | ✅ | Costs 2 energy + 2 Fury power; two chosen damage targets may repeat |
| Charm | ✅ | `move_unit` with `destination: choose` prompts for base or another battlefield |
| Unyielding Spirit | ✅ | `prevent_damage` blocks spell/ability damage for the rest of the turn |

### Gear, Battlefields, Legend

| Card | Status | Gap |
|---|---|---|
| Scrapheap | ⚠️ | `on_play` and `on_discard` draw work; gear `on_death` still lacks an attached-death hook |
| Zaun Warrens | ✅ | `on_conquer` → `discard_then_draw` |
| Targon's Peak | ✅ | `on_conquer` queues delayed `ready_runes` for end of turn |
| Reaver's Row | ✅ | `on_defend` optional `move_unit_to_base` through battlefield trigger dispatch |
| Vilemaw's Lair | ✅ | `no_move_to_base` blocks standard and effect-based moves from that battlefield to base |
| Jinx — Loose Cannon | ✅ | `beginning_phase_start` draw with hand size condition |
| Zhonya's Hourglass | ✅ | `CleanupProcessor` consumes `death_replacement_sacrifice_gear` to sacrifice the Gear and recall/heal/exhaust a dying friendly unit |

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

1. Wire Scrapheap's gear `on_death` to an attached-death or gear-destruction path if that rule is intended for the simulation.
2. Decide whether mandatory triggered abilities with multiple valid targets should prompt instead of auto-picking the first valid target.

### 6.3 Future content hooks

1. Implement unsupported effects only when cards need them: `spend_buff`, `banish`, `gain_xp`, and general `custom`.
2. Add token definitions to `tokens.json` before relying on new `play_token.token_type` values.
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
| Fortified Position (OGN-279) | `battlefields.json` | ✅ `on_defend` grants Shield 2 for the combat (give_keyword, `duration: combat`) — see triggered-target note below |
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
| Meditation (OGN-048) | `spells.json` | ✅ Optional custom cost prompts to exhaust a ready friendly unit; draws 2 if paid, 1 otherwise |
| Gentlemen's Duel (OGS-008) | `spells.json` | ✅ Multi-target buff + fight resolution |
| Highlander (OGS-020) | `spells.json` | ✅ `death_replacement_recall` protects the chosen unit until end of turn |

### Engine features added for this deck

- `CardInstance.passive_might_bonus`, recomputed in `TriggerDispatcher.emit_passive_auras`
  (also called after every command in `GameController.submit_command`). Driven by passive
  `conditional_might` (self) and Legend `aura_might` abilities.
- `ConditionEvaluator`: `rune_count_gte`, `while_combat_alone`, `while_defending_alone`.
- `AbilityResolver`: `channel_rune` now honors `exhausted`; new `channel_rune_or_draw`,
  `give_might_with_alone_bonus`, `units_enter_ready_this_turn`,
  `deal_damage_all_enemies_in_combat`, `fight_chosen_units`, and
  `death_replacement_recall`.
- `PlayerState.channel_rune(enter_exhausted)`, `PlayerState.units_enter_ready_this_turn`,
  and `_place_unit` honoring that flag.
- `GameState.death_replacement_recalls` plus `CleanupProcessor._consume_death_replacement`
  implement Highlander's "next time it would die this turn" replacement, then
  `expire_turn_effects` clears unused protections at end of turn.
- `GameController._queue_spell_target_prompt` queues each `targeting: choose_one`
  resolution ability before putting a spell onto the Chain, so spells such as
  Gentlemen's Duel can carry multiple chosen targets through resolution.
- `ChainProcessor` and `GameController.begin_may_exhaust_friendly_unit_cost` implement
  Meditation's `may_exhaust_friendly_unit` custom cost through an optional prompt followed
  by a target prompt for the unit to exhaust.
- Optional triggered abilities with more than one valid target can prompt for the target
  after the controller accepts the trigger. Reaver's Row and Fortified Position use this
  for `on_defend`.
- Spell/effect movement can ask for a destination with `move_unit` + `destination: "choose"`.
  `GameController._handle_choose_battlefield` resumes the move, and Vilemaw's Lair removes
  `base` from valid destinations through the `no_move_to_base` battlefield keyword.
- `prevent_damage` sets `GameState.prevent_spell_ability_damage` for the turn; `deal_damage`,
  combat-wide spell damage, and chosen-unit fight damage check this flag before adding damage.
- `choose_draw_or_channel` prompts with `choose_mode` when a controller is present, and falls
  back to channel-then-draw behavior for direct resolver simulations without a controller.
- `CleanupProcessor._try_sacrifice_gear_death_replacement` handles
  `death_replacement_sacrifice_gear` directly; it is intentionally not an
  `AbilityResolver` match case.

### Remaining gaps (require further engine work)

1. **General replacement-effect layer.** Highlander's one-card `death_replacement_recall`
   path works by keying a protected unit in `GameState.death_replacement_recalls`.
   Additional replacement effects may need a more general registry if future cards replace
   other events or apply broader scopes.
2. **General custom-cost layer.** Meditation's `may_exhaust_friendly_unit` custom cost is
   explicitly handled by `ChainProcessor`/`GameController`. Other `cost.custom` values still
   require new handlers and tests.
3. **Mandatory triggered target choice.** Optional triggered abilities can prompt for a
   target after `choose yes`; mandatory triggers still use
   `TriggerDispatcher._resolve_trigger_target` and auto-pick the first valid target unless
   a context target is supplied.

### Engine timing fixes (from PR review)

- Conditional passive Might is recomputed (`emit_passive_auras`) **after the Channel Phase**
  and **before lethal-damage checks** (`CleanupProcessor._process_deaths`,
  `CombatProcessor.proceed_to_damage`), not just after player commands, so rune-count and
  "alone" auras are never stale when Might is read.
- `while_combat_alone` / `while_defending_alone` only apply to the unit in the **active**
  combat (`combat_bf_index`), since cleanup designates attacker/defender on every contested
  battlefield.
- `give_keyword` supports `duration: combat`, cleared by `CardInstance.clear_combat_effects`
  in `CombatProcessor.finalize_combat`, so Fortified Position's Shield does not leak past the
  combat or into a later combat the same turn.

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
[ ] gain_xp             [x] gain_points         [x] prevent_damage
[x] cost_reduction      [x] counter_spell       [x] attach
[x] predict             [x] return_to_hand      [x] enter_ready
[x] return_from_trash   [~] custom

[x] discard_then_draw   [x] move_unit_to_base   [x] play_self
[x] gain_keywords       [x] ready_runes
[x] other_friendly_units_enter_ready
[x] deal_damage_equal_to_discarded_energy_cost
[x] channel_rune_or_draw
[x] choose_draw_or_channel
[x] units_enter_ready_this_turn
[x] give_might_with_alone_bonus
[x] deal_damage_all_enemies_in_combat
[x] fight_chosen_units
[x] conditional_might   [x] aura_might
[x] death_replacement_recall
[x] death_replacement_sacrifice_gear

[x] implemented   [~] specific handler exists, but no general framework   [ ] missing
```
