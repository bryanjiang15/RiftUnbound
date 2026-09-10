# Riftbound — Card Data Schema

> Detailed specification for how all card and deck data is represented in JSON.  
> Read alongside `riftbound-resource-plan.md` (§2.1–§2.3 define the folder layout and base schema).

---

## 2.0 ID Conventions

There are two kinds of IDs in the system: **definition IDs** (used in JSON data files) and **instance IDs** (used at runtime in the command console and engine).

### Definition IDs (JSON files)

Definition IDs identify a card type in the data files. They are the **kebab-case version of the card's name**, with no type prefix.

```
"Noxus Hopeful"   → "noxus-hopeful"
"Void Seeker"     → "void-seeker"
"Jinx, Rebel"     → "jinx-rebel"
"Fury Rune"       → "fury-rune"
"Noxus Gates"     → "noxus-gates"
```

- All lowercase, words separated by hyphens.
- Punctuation (commas, apostrophes) is dropped.
- Definition IDs never include a count or suffix — they identify the card type, not a copy.

### Instance IDs (command console & engine)

Instance IDs identify a **specific copy** of a card in play or in hand. They are derived from the definition ID with a numeric suffix appended when more than one copy of the same card is present in the same visible context.

```
First copy:   noxus-hopeful
Second copy:  noxus-hopeful-2
Third copy:   noxus-hopeful-3
```

- The first copy never gets a suffix.
- Suffixes are assigned in the order copies appear (drawn, played, etc.) and re-assigned if a copy leaves play.
- The output log always prints current instance IDs so players know what to type.

### Rune IDs (command console)

Channeled Runes on the board are referred to **by their index** into the player's list of channeled runes (0-based, ordered by the turn they were channeled).

```
rune-0   ← first rune channeled
rune-1   ← second rune channeled
...
rune-11  ← twelfth rune channeled
```

- The `board` and `zones` commands always print the current rune list with indices.
- Rune indices are stable within a session; if a rune is recycled, the remaining runes shift down and are re-indexed.

### Ability IDs (JSON files only)

Ability IDs are used internally in the data files to link abilities to their handlers. They are **not typed by players** in the console. Format: `<card-definition-id>-<short-description>`.

```
"noxus-hopeful-legion-cost"
"fury-rune-tap"
"fury-rune-recycle"
"void-seeker-damage"
"void-seeker-draw"
```

---

## 2.4 Ability Schema

Abilities are defined as structured objects. They are **not free-form text** in the engine — each ability maps to a **handler function** in GDScript by its `effect_type`.

```json
{
  "ability_id": "string — unique per card, e.g. 'jinx-rebel-play-effect'",
  "ability_type": "passive | triggered | activated | replacement",
  "timing": "play | hold | conquer | attack | defend | end_of_turn | start_of_turn | on_death | on_move | on_damage | null",
  "condition": {
    "type": "string — 'legion' | 'hand_size_lte' | 'discarded_card_this_turn' | 'might_lte' | 'rune_count_gte' | 'while_combat_alone' | 'while_defending_alone' | null",
    "value": "optional"
  },
  "is_optional": false,
  "cost": {
    "energy": 0,
    "power": [],
    "exhaust": false,
    "recycle": 0,
    "discard": 0,
    "kill_friendly": false,
    "recycle_self": false,
    "custom": "string — for complex costs"
  },
  "effect_type": "string — maps to a GDScript handler",
  "effect_params": { },
  "is_action": false,
  "is_reaction": false
}
```

### Field Notes

| Field | Values | Notes |
|---|---|---|
| `ability_type` | `passive`, `triggered`, `activated`, `replacement` | Determines when/how the ability is evaluated |
| `timing` | See list above | For triggered abilities: when the trigger fires. `null` for passives and activated abilities |
| `condition.type` | See Implemented Conditions below | Evaluated by `ConditionEvaluator.gd`. `null` or an empty string means always active |
| `is_optional` | `true` / `false` | If `true`, the controller chooses whether to trigger/activate |
| `cost` | object | All cost sub-fields default to zero/false if omitted |
| `effect_type` | string | Must match a key in the Effect Type Registry (§2.5) |
| `effect_params` | object | Shape varies by `effect_type` — see §2.5 |
| `is_action` | `true` / `false` | Can be used during Showdowns |
| `is_reaction` | `true` / `false` | Can be used during Closed States on any player's turn |

### Implemented Conditions

`ConditionEvaluator.gd` treats unknown condition types as `true`, so card authors should use only the implemented names below unless they also add evaluator coverage and tests.

| `condition.type` | Required fields | Runtime meaning |
|---|---|---|
| `legion` | none | Controller has played another card this turn (`cards_played_this_turn > 0`) |
| `hand_size_lte` | `value` | Controller's hand size is less than or equal to `value` |
| `discarded_card_this_turn` | none | Controller has discarded at least one card this turn |
| `might_lte` | `value` | Target's current Might, including passive/temporary/keyword bonuses, is less than or equal to `value` |
| `rune_count_gte` | `value` | Controller has at least `value` channeled runes |
| `played_card_type` | `card_type` | Source controller just played a card of the given type, e.g. `"spell"` |
| `played_card_count_eq` | `value` | Source controller has played exactly `value` cards this turn after the current play |
| `while_combat_alone` | none | Source unit is the sole friendly unit at the active combat battlefield and is attacking or defending |
| `while_defending_alone` | none | Source unit is defending alone at the active combat battlefield |

Combat-alone conditions are gated by `GameState.combat_bf_index`. Cleanup can designate units on multiple contested battlefields, but only the active combat receives the bonus.

---

## 2.5 Effect Type Registry

Each `effect_type` string maps to a handler in `AbilityResolver.gd` unless the notes name a different subsystem. Keep this registry in sync with the resolver `match` block and `TriggerDispatcher.emit_passive_auras()`.

| `effect_type` | Description | Key `effect_params` |
|---|---|---|
| `"add_energy"` | Add Energy to the controller's Rune Pool | `{ "amount": 2 }` |
| `"add_power"` | Add domain Power to the controller's Rune Pool. `"spell_rainbow"` can pay any domain Power cost only while playing spells. | `{ "domain": "fury", "amount": 1 }` |
| `"draw"` | Draw cards; Burn Out scoring applies when the deck recycles from trash | `{ "amount": 1 }` |
| `"deal_damage"` | Deal fixed damage to a chosen/resolved target | `{ "amount": 4, "target": "unit_at_battlefield", "targeting": "choose_one" }` |
| `"heal"` | Heal target damage; `"all"` clears all damage | `{ "amount": "all", "target": "friendly_unit" }` |
| `"kill"` | Move a target permanent to trash | `{ "target": "enemy_unit" }` |
| `"give_might"` | Add temporary Might for a duration currently modeled as this turn. Negative values may include `minimum_might` to clamp current Might. | `{ "amount": 3, "duration": "turn", "target": "friendly_unit" }` |
| `"give_keyword"` | Grant a temporary keyword. `duration` may be `"turn"`, `"combat"`, or omitted; `temporary` defaults to Beginning Phase cleanup | `{ "keyword": { "id": "shield", "value": 2 }, "duration": "combat" }` |
| `"buff_unit"` | Place one Buff counter on the target unit | `{ "target": "friendly_unit" }` |
| `"move_unit"` | Move target unit to base or to a chosen battlefield. `destination: "choose"` prompts with `choose_battlefield`; the `no_move_to_base` battlefield keyword removes `base` as a valid choice. Moving to an enemy-controlled or occupied battlefield contests it. | `{ "target": "enemy_unit", "targeting": "choose_one", "destination": "choose" }` |
| `"move_unit_to_base"` | Move a battlefield unit to its owner's base exhausted | `{ "target": "unit_at_battlefield", "targeting": "choose_one" }` |
| `"stun_unit"` | Mark a target unit Stunned | `{ "target": "enemy_unit" }` |
| `"recycle"` | Return cards from trash to hand in current implementation | `{ "from": "trash", "amount": 1 }` |
| `"recycle_from_trash"` | Recycle up to N cards from controller trash to the bottom of the main deck | `{ "amount": 3 }` |
| `"discard"` | Discard cards from hand; controller prompts preserve `on_discard` triggers | `{ "amount": 1 }` |
| `"discard_then_draw"` | Prompt for discards, then draw after the discard continuation resolves | `{ "discard_amount": 1, "draw_amount": 1 }` |
| `"channel_rune"` | Channel additional rune(s); can enter exhausted | `{ "amount": 1, "exhausted": true }` |
| `"channel_rune_or_draw"` | Channel rune(s), or draw if the rune deck is empty | `{ "channel_amount": 1, "exhausted": true, "draw_amount": 1 }` |
| `"units_enter_ready_this_turn"` | Set a player flag so units played later this turn enter ready | `{}` |
| `"give_might_with_alone_bonus"` | Give Might and add a bonus if the target is the only friendly unit at its location | `{ "amount": 1, "alone_bonus": 1, "target": "friendly_unit" }` |
| `"deal_damage_all_enemies_in_combat"` | During combat, damage every enemy unit at `combat_bf_index` | `{ "amount": 2 }` |
| `"fight_chosen_units"` | Use the spell's first chosen target as the buffed friendly unit and this ability's target as the enemy; both deal current Might to each other | `{ "target": "enemy_unit", "targeting": "choose_one" }` |
| `"ready_permanent"` | Ready a target permanent | `{ "target": "friendly_unit" }` |
| `"ready_runes"` | Ready up to N channeled runes; `TriggerDispatcher` can queue this for end of turn | `{ "amount": 2, "timing": "end_of_turn" }` |
| `"play_token"` | Create and play a token definition, if present in `tokens.json`; `location: "here"` follows the source's battlefield when possible | `{ "token_type": "sprite-3m", "location": "here", "ready": true }` |
| `"gain_points"` | Gain Victory Points | `{ "amount": 1 }` |
| `"counter_spell"` | Remove the top spell/ability from the chain | `{ "target": "spell_on_chain" }` |
| `"predict"` | Reveal top cards in logs; recycle choice is not modeled | `{ "amount": 2 }` |
| `"return_to_hand"` | Return a permanent to its owner's hand | `{ "target": "unit_at_battlefield" }` |
| `"enter_ready"` | Ready the source card as it enters; used by Accelerate-style abilities | `{}` |
| `"return_from_trash"` | Return a matching trash card to hand; prompts with `choose_trash_return` when multiple matches exist | `{ "target": "unit" }` |
| `"other_friendly_units_enter_ready"` | Special-cased after a unit is played; readies other friendly units already on board/base | `{}` |
| `"gain_keywords"` | Append passive keywords to the source when passive auras refresh | `{ "keywords": [{ "id": "assault", "value": 1 }] }` |
| `"play_self"` | Move the source card from trash to base after its ability cost is paid | `{}` |
| `"deal_damage_equal_to_discarded_energy_cost"` | Damage target by the Energy cost of the most recently discarded card this turn | `{ "target": "unit_at_battlefield", "targeting": "choose_one" }` |
| `"cost_reduction"` | Read by `CostCalculator`; resolver intentionally does nothing | `{ "amount": 2, "scope": "self", "duration": "play" }` |
| `"attach"` | Attach this Gear to a target unit | `{ "target": "friendly_unit" }` |
| `"death_replacement_recall"` | Protect a chosen friendly unit from its next death this turn; cleanup heals, exhausts, and recalls it instead | `{ "target": "friendly_unit", "targeting": "choose_one", "duration": "turn" }` |
| `"death_replacement_sacrifice_gear"` | Read by `CleanupProcessor`, not `AbilityResolver`: sacrifice the Gear, heal/exhaust/recall the dying friendly unit, and move the Gear to trash. | `{ "target": "friendly_unit" }` |
| `"prevent_damage"` | Prevent spell/ability damage for the rest of the turn. Current resolver support is limited to `source: "spells_and_abilities"` or `"all"`; turn cleanup clears the flag. | `{ "source": "spells_and_abilities", "duration": "turn", "scope": "all" }` |
| `"choose_draw_or_channel"` | Prompt the controller to `choose draw` or `choose channel`; direct resolver simulations without a controller channel first if possible, otherwise draw. | `{ "draw_amount": 1, "channel_amount": 1, "exhausted": true }` |

Passive aura effects are refreshed by `TriggerDispatcher.emit_passive_auras()` rather than normal chain resolution:

| `effect_type` | Description | Key `effect_params` |
|---|---|---|
| `"conditional_might"` | Add to a unit's `passive_might_bonus` while its condition evaluates true; may scale by controller trash size | `{ "amount": 2 }` or `{ "per_card_in_trash": true, "amount_per_card": 1 }` |
| `"aura_might"` | Legend aura that adds Might to each friendly unit whose condition evaluates true | `{ "target": "friendly_unit", "amount": 2 }` |
| `"gain_keywords"` | Add passive keywords while the source's condition evaluates true | `{ "keywords": [{ "id": "ganking" }] }` |

Declared but unsupported effect names should be treated as gaps until a handler and tests are added: `"spend_buff"`, `"banish"`, `"gain_xp"`, and `"custom"` (general bespoke behavior; known custom cost strings such as `"may_exhaust_friendly_unit"` are handled explicitly by the chain/controller path).

### Multi-Target Spell Resolution

For spells with multiple resolution abilities that each use `targeting: "choose_one"`, `GameController._queue_spell_target_prompt()` prompts for each target before the spell is put onto the Chain. The resulting `ChainItem.targets` array is passed to the resolver as `ctx.chosen_targets`; `fight_chosen_units` uses the first chosen target as the friendly unit buffed by Gentlemen's Duel and the second target as the enemy fight target.

### Triggered Ability Target Prompts

Triggered abilities normally resolve their first valid target from `TargetResolver`. Optional triggered abilities with more than one valid target prompt in two steps: `choose yes` / `choose no`, then `choose <instance-id>` for the target. This is used by battlefield `on_defend` abilities such as Reaver's Row and Fortified Position.

### Target Value Reference

The `"target"` field in `effect_params` uses the following string values:

| Value | Meaning |
|---|---|
| `"self"` | The card/permanent this ability belongs to |
| `"friendly_unit"` | Any unit the controller controls |
| `"enemy_unit"` | Any unit an opponent controls |
| `"unit_at_battlefield"` | Any unit at any battlefield |
| `"friendly_unit_at_battlefield"` | Friendly unit specifically at a battlefield |
| `"enemy_unit_at_battlefield"` | Enemy unit at a battlefield |
| `"friendly_unit_here"` | Friendly unit at the event battlefield from trigger context |
| `"friendly_gear"` | Any gear the controller controls |
| `"enemy_gear"` | Any gear an opponent controls |
| `"unit_or_gear_at_battlefield"` | Any unit at a battlefield plus unattached Gear at base |
| `"spell_on_chain"` | A spell or ability currently on the chain |
| `"top_of_deck"` | Top card(s) of the controller's main deck |
| `"card_in_trash"` | A card in the controller's trash |
| `"unit"` | Unit cards in trash; used by `return_from_trash` |
| `"any_unit"` | Any unit regardless of controller |
| `"all_friendly_units"` | All units the controller controls (no choice) |
| `"all_enemy_units"` | All units opponents control (no choice) |
| `"all_units_at_battlefield"` | All units at a specific battlefield |

---

## 2.6 Keyword Schema

Keywords with values are stored on the card directly. The engine reads them at the appropriate game moment.

```json
"keywords": [
  { "id": "assault", "value": 2 },
  { "id": "shield", "value": 1 },
  { "id": "tank" },
  { "id": "accelerate" },
  { "id": "ganking" },
  { "id": "deflect", "value": 1 },
  { "id": "deathknell" },
  { "id": "hidden" },
  { "id": "temporary" },
  { "id": "vision" },
  { "id": "legion" },
  { "id": "action" },
  { "id": "reaction" }
]
```

### Keyword Reference

| `id` | Has `value`? | Engine Behavior |
|---|---|---|
| `"accelerate"` | No | Optional +1 Energy +1 Power cost when playing to enter Ready |
| `"action"` | No | Can be played during Showdowns |
| `"assault"` | Yes | +`value` Might while unit has Attacker designation |
| `"deathknell"` | No | Paired ability fires before unit moves to Trash |
| `"deflect"` | Yes | Enemy spells/abilities targeting this cost `value` extra Power |
| `"ganking"` | No | Unit may Standard Move from Battlefield to Battlefield |
| `"hidden"` | No | Can be placed face-down at controlled Battlefield for `[A]`; playable for free next turn with Reaction timing |
| `"legion"` | No | Linked ability is active only if controller played another card this turn |
| `"no_move_to_base"` | No | Battlefield keyword: units at this battlefield cannot move to base through standard movement or `move_unit` / `move_unit_to_base` effects |
| `"reaction"` | No | Can be played during Closed States on any player's turn |
| `"shield"` | Yes | +`value` Might while unit has Defender designation |
| `"tank"` | No | Must be assigned lethal damage before non-Tank friendly units in combat |
| `"temporary"` | No | Killed at the start of controller's next Beginning Phase (before scoring) |
| `"vision"` | No | Declared keyword only; no current engine implementation or card data uses it |

---

## 2.7 Full Example — Unit

```json
{
  "id": "noxus-hopeful",
  "name": "Noxus Hopeful",
  "card_type": "unit",
  "supertypes": [],
  "tags": ["Noxus"],
  "domain": ["fury"],
  "energy_cost": 2,
  "power_cost": [],
  "might": 3,
  "might_bonus": null,
  "keywords": [
    { "id": "legion" }
  ],
  "abilities": [
    {
      "ability_id": "noxus-hopeful-legion-cost",
      "ability_type": "passive",
      "timing": null,
      "condition": { "type": "legion" },
      "is_optional": false,
      "cost": { "energy": 0, "power": [], "exhaust": false },
      "effect_type": "cost_reduction",
      "effect_params": { "amount": 2, "scope": "self", "duration": "play" },
      "is_action": false,
      "is_reaction": false
    }
  ],
  "flavor_text": "The first step is always the hardest."
}
```

---

## 2.8 Full Example — Basic Rune

```json
{
  "id": "fury-rune",
  "name": "Fury Rune",
  "card_type": "rune",
  "supertypes": [],
  "tags": [],
  "domain": ["fury"],
  "energy_cost": 0,
  "power_cost": [],
  "is_basic": true,
  "keywords": [],
  "abilities": [
    {
      "ability_id": "fury-rune-tap",
      "ability_type": "activated",
      "timing": null,
      "condition": null,
      "is_optional": true,
      "cost": { "energy": 0, "power": [], "exhaust": true },
      "effect_type": "add_energy",
      "effect_params": { "amount": 1 },
      "is_action": false,
      "is_reaction": true
    },
    {
      "ability_id": "fury-rune-recycle",
      "ability_type": "activated",
      "timing": null,
      "condition": null,
      "is_optional": true,
      "cost": { "energy": 0, "power": [], "exhaust": false, "recycle_self": true },
      "effect_type": "add_power",
      "effect_params": { "domain": "fury", "amount": 1 },
      "is_action": false,
      "is_reaction": true
    }
  ]
}
```

---

## 2.9 Full Example — Spell

```json
{
  "id": "void-seeker",
  "name": "Void Seeker",
  "card_type": "spell",
  "supertypes": [],
  "tags": [],
  "domain": ["chaos"],
  "energy_cost": 4,
  "power_cost": [],
  "keywords": [],
  "is_action": false,
  "is_reaction": false,
  "abilities": [
    {
      "ability_id": "void-seeker-damage",
      "ability_type": "triggered",
      "timing": "resolution",
      "condition": null,
      "is_optional": false,
      "cost": {},
      "effect_type": "deal_damage",
      "effect_params": {
        "amount": 4,
        "target": "unit_at_battlefield",
        "targeting": "choose_one"
      },
      "is_action": false,
      "is_reaction": false
    },
    {
      "ability_id": "void-seeker-draw",
      "ability_type": "triggered",
      "timing": "resolution",
      "condition": null,
      "is_optional": false,
      "cost": {},
      "effect_type": "draw",
      "effect_params": { "amount": 1 },
      "is_action": false,
      "is_reaction": false
    }
  ]
}
```

---

## 2.10 Deck File Format

```json
{
  "deck_id": "starter-fury-p1",
  "player_label": "Player 1",
  "legend": "jinx",
  "chosen_champion": "jinx-rebel",
  "main_deck": [
    { "card_id": "jinx-rebel", "count": 1 },
    { "card_id": "noxus-hopeful", "count": 3 },
    { "card_id": "void-seeker", "count": 2 }
  ],
  "rune_deck": [
    { "card_id": "fury-rune", "count": 12 }
  ],
  "battlefields": [
    "noxus-gates",
    "training-grounds",
    "shattered-colosseum"
  ]
}
```

### Deck File Field Notes

| Field | Notes |
|---|---|
| `legend` | Must reference a valid `id` in `legends.json` |
| `chosen_champion` | Must reference a champion unit whose champion tag matches the legend's `champion_tag` |
| `main_deck` | Must total ≥ 40 cards. Max 3 copies of any one `card_id`. Max 3 total Signature cards |
| `rune_deck` | Must total exactly 12 runes |
| `battlefields` | List of 3 `card_id` values from `battlefields.json`. One is randomly selected at game start |
