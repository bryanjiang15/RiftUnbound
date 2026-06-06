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
    "type": "string — 'legion' | 'level' | 'while_alone' | 'while_attacking' | 'while_defending' | 'if_mighty' | null",
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
| `condition.type` | `legion`, `level`, `while_alone`, `while_attacking`, `while_defending`, `if_mighty`, `null` | Dependent keyword conditions. `null` means always active |
| `is_optional` | `true` / `false` | If `true`, the controller chooses whether to trigger/activate |
| `cost` | object | All cost sub-fields default to zero/false if omitted |
| `effect_type` | string | Must match a key in the Effect Type Registry (§2.5) |
| `effect_params` | object | Shape varies by `effect_type` — see §2.5 |
| `is_action` | `true` / `false` | Can be used during Showdowns |
| `is_reaction` | `true` / `false` | Can be used during Closed States on any player's turn |

---

## 2.5 Effect Type Registry

Each `effect_type` string maps to a handler in `AbilityResolver.gd`. The following effect types cover the base game:

| `effect_type` | Description | Key `effect_params` |
|---|---|---|
| `"add_energy"` | Add N Energy to Rune Pool | `{ "amount": 2 }` |
| `"add_power"` | Add N Power of domain to Rune Pool | `{ "domain": "fury", "amount": 1 }` |
| `"draw"` | Draw N cards | `{ "amount": 1 }` |
| `"deal_damage"` | Deal N damage to target(s) | `{ "amount": 3, "target": "unit_at_battlefield", "split": false }` |
| `"heal"` | Heal N damage from target | `{ "amount": "all", "target": "friendly_unit" }` |
| `"kill"` | Kill a target permanent | `{ "target": "enemy_unit" }` |
| `"give_might"` | Give unit +N Might (this turn or permanent) | `{ "amount": 2, "duration": "turn" }` |
| `"give_keyword"` | Grant a keyword to a unit | `{ "keyword": "shield", "value": 2, "duration": "turn" }` |
| `"buff_unit"` | Place a Buff counter on a unit | `{ "target": "friendly_unit" }` |
| `"spend_buff"` | Spend a Buff counter | `{ "target": "self" }` |
| `"move_unit"` | Move a unit to a location | `{ "target": "friendly_unit", "destination": "any_battlefield" }` |
| `"stun_unit"` | Stun a unit | `{ "target": "enemy_unit" }` |
| `"banish"` | Banish card(s) | `{ "target": "top_of_deck", "amount": 1 }` |
| `"recycle"` | Recycle card(s) to deck | `{ "from": "trash", "amount": 1 }` |
| `"discard"` | Discard N cards from hand (player chooses which cards; `on_discard` triggers fire) | `{ "amount": 1 }` |
| `"channel_rune"` | Channel additional rune(s) | `{ "amount": 1, "exhausted": false }` |
| `"ready_permanent"` | Ready a permanent | `{ "target": "friendly_unit" }` |
| `"play_token"` | Create and play a token | `{ "token_type": "recruit_1m", "location": "base" }` |
| `"gain_xp"` | Gain N XP | `{ "amount": 1 }` |
| `"gain_points"` | Gain N Victory Points | `{ "amount": 1 }` |
| `"prevent_damage"` | Prevent next N damage | `{ "amount": 3, "target": "self", "duration": "turn" }` |
| `"cost_reduction"` | Reduce cost of cards | `{ "amount": 1, "scope": "spells", "duration": "turn" }` |
| `"counter_spell"` | Counter a spell/ability on the chain | `{ "target": "spell_on_chain" }` |
| `"attach"` | Attach this gear to a unit | `{ "target": "friendly_unit" }` |
| `"predict"` | Look at top N cards; recycle any | `{ "amount": 2 }` |
| `"return_to_hand"` | Return a permanent to its owner's hand | `{ "target": "friendly_unit" }` |
| `"custom"` | Complex effect — handled by card-specific script | `{ "script": "res://Scripts/Cards/Special/card_id.gd" }` |

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
| `"friendly_gear"` | Any gear the controller controls |
| `"enemy_gear"` | Any gear an opponent controls |
| `"spell_on_chain"` | A spell or ability currently on the chain |
| `"top_of_deck"` | Top card(s) of the controller's main deck |
| `"card_in_trash"` | A card in the controller's trash |
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
| `"reaction"` | No | Can be played during Closed States on any player's turn |
| `"shield"` | Yes | +`value` Might while unit has Defender designation |
| `"tank"` | No | Must be assigned lethal damage before non-Tank friendly units in combat |
| `"temporary"` | No | Killed at the start of controller's next Beginning Phase (before scoring) |
| `"vision"` | No | When played: look at top card of Main Deck; may Recycle it |

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
