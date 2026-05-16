# Riftbound — Game Resource Plan

> No card art. No audio. Placeholder visuals only.  
> Focus: what textures are needed, and how card/ability data is structured.

---

## 1. Visual Resource List

### 1.1 Card Frame & Back (Shared Across All Types)

No artwork. All cards use a **single shared frame and back texture**. Card type is communicated purely through text labels and domain/cost icons overlaid on the frame. All text is rendered via Godot's `Label` nodes.


| Asset Name       | Description                                                          |
| ---------------- | -------------------------------------------------------------------- |
| `card_frame.png` | Shared frame for all card types                                      |
| `card_back.png`  | Shared back for all cards (used for face-down cards and deck stacks) |


> Fixed size, e.g. **140 × 200 px**. Text and icons laid over the frame via scene composition.

---

### 1.2 Domain Icons

One small icon per domain, used on cards and in the resource display.

**For now, use colors to indicate what domain it is instead of using the png**


| Asset Name         | Domain          | Color           |
| ------------------ | --------------- | --------------- |
| `domain_fury.png`  | Fury (R)        | Red             |
| `domain_calm.png`  | Calm (G)        | Green           |
| `domain_mind.png`  | Mind (B)        | Blue            |
| `domain_body.png`  | Body (O)        | Orange          |
| `domain_chaos.png` | Chaos (P)       | Purple          |
| `domain_order.png` | Order (Y)       | Yellow          |
| `domain_any.png`   | Universal `[A]` | Rainbow / White |


> Suggested size: **24 × 24 px** icons. Placeholder: colored circles with a 1–2 letter label.

---

### 1.3 Resource / Cost Symbols

Used in card cost display and in the Rune Pool HUD.

**For now use text achronym to represent the icon**


| Asset Name             | Represents            | Notes |
| ---------------------- | --------------------- | ----- |
| `icon_energy.png`      | Energy `[1]`          | ENG   |
| `icon_power_fury.png`  | Fury Power            | FRY   |
| `icon_power_calm.png`  | Calm Power            | CLM   |
| `icon_power_mind.png`  | Mind Power            | MND   |
| `icon_power_body.png`  | Body Power            | BDY   |
| `icon_power_chaos.png` | Chaos Power           | CHS   |
| `icon_power_order.png` | Order Power           | ORD   |
| `icon_power_any.png`   | Universal Power `[A]` | ANY   |
| `icon_exhaust.png`     | Exhaust cost `[E]`    | EXH   |
| `icon_might.png`       | Might `[M]`           | MHT   |


> Suggested size: **24 × 24 px**. Placeholder: colored squares with text label.

---

### 1.4 Status Markers (In-game overlays on cards)

Rendered as small overlaid icons or color tints on the card node. Use text to represent them instead of visuals for now


| Asset Name              | Represents                | Visual                                          |
| ----------------------- | ------------------------- | ----------------------------------------------- |
| `marker_exhausted.png`  | Card is Exhausted         | Semi-transparent dark overlay + rotate card 90° |
| `marker_buff.png`       | Buff counter (+1 Might)   | Small gold star or "B" badge                    |
| `marker_stunned.png`    | Unit is Stunned           | Yellow lightning bolt badge                     |
| `marker_damage.png`     | Damage counter            | Red number badge (shown as a `Label`)           |
| `marker_attacker.png`   | Has Attacker designation  | Red sword badge                                 |
| `marker_defender.png`   | Has Defender designation  | Blue shield badge                               |
| `marker_contested.png`  | Battlefield is Contested  | Orange outline on battlefield panel             |
| `marker_controlled.png` | Battlefield is Controlled | Player-color outline                            |


> Exhaustion is represented by rotating the card node -90 degrees, not a separate texture.

---

### 1.5 Board UI (Zones and Layout)

These are panel backgrounds and zone indicators for the game board scene. **Use rectangles to represent them for now**


| Asset Name                           | Represents                                               |
| ------------------------------------ | -------------------------------------------------------- |
| `zone_base_p1.png`                   | Player 1's Base area background                          |
| `zone_base_p2.png`                   | Player 2's Base area background                          |
| `zone_hand.png`                      | Hand area background (bottom of screen for local player) |
| `zone_battlefield_slot.png`          | Empty Battlefield slot placeholder                       |
| `zone_battlefield_controlled_p1.png` | Battlefield slot with P1 control highlight               |
| `zone_battlefield_controlled_p2.png` | Battlefield slot with P2 control highlight               |
| `zone_deck_main.png`                 | Main Deck stack indicator                                |
| `zone_deck_rune.png`                 | Rune Deck stack indicator                                |
| `zone_trash.png`                     | Trash zone indicator                                     |
| `zone_champion.png`                  | Champion Zone slot                                       |
| `zone_legend.png`                    | Legend Zone slot                                         |
| `zone_facedown_slot.png`             | Facedown (Hidden) zone slot per Battlefield              |
| `zone_banishment.png`                | Banishment zone indicator                                |
| `board_background.png`               | Full board background texture                            |


> All zone panels can be simple colored `StyleBoxFlat` panels in Godot — no texture file required if using theme styles.

---

### 1.6 HUD & UI Chrome


| Asset Name         | Represents                                           |
| ------------------ | ---------------------------------------------------- |
| `hud_panel.png`    | General UI panel background (dark, semi-transparent) |
| `btn_normal.png`   | Button idle state                                    |
| `btn_hover.png`    | Button hover state                                   |
| `btn_pressed.png`  | Button pressed state                                 |
| `icon_score.png`   | Point/score icon (star or trophy)                    |
| `icon_turn.png`    | Turn indicator arrow                                 |
| `icon_phase.png`   | Phase indicator badge                                |
| `icon_victory.png` | Win screen overlay                                   |


---

### 1.7 Chain / Stack Indicator


| Asset Name           | Represents                                              |
| -------------------- | ------------------------------------------------------- |
| `chain_item_bg.png`  | Background for a single chain item in the stack display |
| `chain_panel_bg.png` | Background panel for the full chain display             |


---

## 2. Card Data Format

Cards are defined in **JSON** files. All game logic reads from these files at runtime (or they are converted to Godot `Resource` files via an import script).

### 2.1 Folder Structure

```
res://Data/
  Cards/
    units.json
    gear.json
    spells.json
    runes.json
    battlefields.json
    legends.json
  Decks/
    starter-deck-p1.json
    starter-deck-p2.json
```

---

### 2.2 Base Card Schema (all types share these fields)

```json
{
  "id": "string — kebab-case card name, e.g. 'jinx-rebel'",
  "name": "string — display name, e.g. 'Jinx, Rebel'",
  "card_type": "string — 'unit' | 'gear' | 'spell' | 'rune' | 'battlefield' | 'legend'",
  "supertypes": ["champion", "signature", "token"],
  "tags": ["Jinx", "Piltover", "Zaun"],
  "domain": ["fury"],
  "energy_cost": 3,
  "power_cost": [
    { "domain": "fury", "amount": 1 }
  ],
  "keywords": ["accelerate", "assault"],
  "abilities": [ /* see §2.4 */ ],
  "flavor_text": "optional string"
}
```

---

### 2.3 Type-Specific Fields

**Unit** (extends base):

```json
{
  "might": 4,
  "might_bonus": null
}
```

**Gear** (extends base):

```json
{
  "might_bonus": "+2",
  "effect_text_abilities": [ /* abilities active when attached */ ]
}
```

**Spell** (extends base):

```json
{
  "is_action": false,
  "is_reaction": false
}
```

**Rune** (extends base):

```json
{
  "is_basic": true
}
```

> Basic Runes always have two fixed abilities (see `riftbound-card-data-schema.md` §2.8 — pre-defined ability IDs `"basic_rune_tap"` and `"basic_rune_recycle"`).

**Battlefield** (extends base):

```json
{
  "facedown_capacity": 1
}
```

**Legend** (extends base):

```json
{
  "champion_tag": "Jinx"
}
```

---

> **§2.4 – §2.10** (Ability schema, effect type registry, keyword schema, full card examples, and deck file format) are documented in detail in:
> 📄 [`riftbound-card-data-schema.md`](./riftbound-card-data-schema.md)

---

## 3. Token Definitions

Tokens are not stored in card files — they are defined in a **tokens registry** since they are created at runtime.

```json
{
  "token_id": "recruit_1m",
  "name": "Recruit",
  "card_type": "unit",
  "supertypes": ["token"],
  "tags": ["Recruit"],
  "domain": [],
  "energy_cost": 0,
  "might": 1,
  "keywords": [],
  "abilities": []
}
```

**Registered tokens for base game:**


| Token ID          | Type | Might | Tags    | Keywords                                |
| ----------------- | ---- | ----- | ------- | --------------------------------------- |
| `recruit_1m`      | unit | 1     | Recruit | —                                       |
| `sprite_3m`       | unit | 3     | Fae     | Temporary                               |
| `sand_soldier_2m` | unit | 2     | Shurima | —                                       |
| `mech_3m`         | unit | 3     | Mech    | —                                       |
| `reflection_0m`   | unit | 0     | —       | —                                       |
| `bird_1m`         | unit | 1     | Bird    | Deflect                                 |
| `gold_gear`       | gear | —     | —       | `[Reaction][>] Kill this, [E]: Add [A]` |


---

## 4. Godot Scene & Script Summary

The following scenes consume the data above:


| Scene                  | Textures Used                                                           | Data Consumed                 |
| ---------------------- | ----------------------------------------------------------------------- | ----------------------------- |
| `CardView.tscn`        | card_frame.png, card_back.png, domain icons, cost icons, status markers | Card JSON → CardData resource |
| `BoardView.tscn`       | zone_*.png, board_background.png                                        | —                             |
| `BattlefieldSlot.tscn` | zone_battlefield_*.png, marker_contested.png                            | Battlefield card JSON         |
| `HandStrip.tscn`       | — (hosts CardViews)                                                     | Player hand array             |
| `RunePool.tscn`        | icon_energy.png, icon_power_*.png                                       | Rune Pool state               |
| `ChainPanel.tscn`      | chain_item_bg.png, chain_panel_bg.png                                   | Chain item list               |
| `ScoreHUD.tscn`        | icon_score.png, icon_turn.png, icon_phase.png                           | Game state                    |
| `PhaseIndicator.tscn`  | icon_phase.png                                                          | Current turn phase enum       |


---

## 5. File Summary

```
res://
  Assets/
    Textures/
      Cards/
        card_frame.png
        card_back.png
      Domains/
        domain_fury.png
        domain_calm.png
        domain_mind.png
        domain_body.png
        domain_chaos.png
        domain_order.png
        domain_any.png
      Icons/
        icon_energy.png
        icon_power_fury.png  (x6 domains + any)
        icon_exhaust.png
        icon_might.png
        icon_score.png
        icon_turn.png
        icon_phase.png
        icon_victory.png
      Markers/
        marker_buff.png
        marker_stunned.png
        marker_attacker.png
        marker_defender.png
        marker_contested.png
      UI/
        hud_panel.png
        btn_normal.png
        btn_hover.png
        btn_pressed.png
        chain_item_bg.png
        chain_panel_bg.png

  Data/
    Cards/
      units.json
      gear.json
      spells.json
      runes.json
      battlefields.json
      legends.json
      tokens.json
    Decks/
      starter-deck-p1.json
      starter-deck-p2.json
```

---

## 6. Notes on Placeholder Strategy

Since no card art is used in the initial implementation:

- **Card frame + type color + text** is sufficient to represent all cards visually.
- Domain icons and cost icons provide the only meaningful visual differentiation between cards.
- All card frames can be generated with Godot's `StyleBoxFlat` at runtime — no texture files required for frames initially. The `card_frame_*.png` files can be added later when polishing.
- Status markers (buff, stun, damage) can be `Label` nodes overlaid on the card node with colored backgrounds — no dedicated texture files needed initially.
- Domain icons are the highest-priority visual assets since they appear in multiple places (card costs, HUD, zone indicators).
- Exhaustion is represented by **rotating the card node 90°** — no extra texture.

**Minimum viable texture set to start:**

1. 7 domain/power icons (6 domains + universal)
2. `icon_energy.png`
3. `icon_might.png`
4. `icon_exhaust.png`
5. `board_background.png`

