# Riftbound — Implementation Reference Rules

> Distilled from the Core Rules (2026-03-30). Focused on what affects game logic.

---

## 1. Deck Construction

| Component | Details |
|---|---|
| Champion Legend | 1 per player. Placed in Legend Zone. Defines the **Domain Identity** (which domains cards in the deck may use). |
| Main Deck | ≥ 40 cards: 1 Chosen Champion + Units + Gear + Spells. Max 3 copies of any one name. Max 3 total Signature cards. |
| Rune Deck | Exactly 12 Rune cards. Separate from Main Deck. |
| Battlefields | Quantity per Mode of Play. Not shuffled into a deck. |

**Domain Identity:** Cards must belong only to domains present on the Champion Legend.  
**Chosen Champion:** A Champion Unit placed face-up in the Champion Zone at game start. Can be played from there. Any copy of the same-named unit in the deck/hand/trash also counts as the Chosen Champion.

---

## 2. Game Setup

1. Each player places their **Champion Legend** in the Legend Zone.  
2. Each player places their **Chosen Champion** in the Champion Zone.  
3. Battlefields are placed in the Battlefield Zone (count per mode).  
4. Each player shuffles and places their **Main Deck** and **Rune Deck** separately.  
5. Determine **Turn Order** randomly.  
6. Each player draws **4 cards**.  
7. In turn order, each player performs a **Mulligan**: set aside up to 2 cards, draw replacements, then Recycle the set-aside cards.  
8. First Player takes their turn.

**1v1 (Duel/Match):** 2 players. 2 Battlefields (each player contributes 3, one is randomly selected). Victory Score: **8 points**. Player going second channels 1 extra Rune on their first Channel Phase.

---

## 3. Zones

### Board Zones (Public unless noted)
| Zone | Description |
|---|---|
| **Base** | Each player has one. Permanents and Runes they control reside here. |
| **Battlefield Zone** | Contains all Battlefields (Locations where Units fight and Scores happen). |
| **Facedown Zone** | One per Battlefield. Max 1 facedown card (from the Hidden keyword). Private info. |
| **Legend Zone** | Holds each player's Champion Legend. Cannot be removed. Not a location. |

### Non-Board Zones
| Zone | Info Level |
|---|---|
| **Hand** | Private (count is Public). |
| **Main Deck** | Secret. |
| **Rune Deck** | Secret. |
| **Trash** | Public. Unordered. |
| **Banishment** | Public. Unordered. |
| **Champion Zone** | Public. Holds Chosen Champion until played. |
| **The Chain** | Temporary. Public. Exists when a card/ability is being played. |

**Key rule:** When a card changes zones to/from a Non-Board Zone, all temporary modifications (damage, buffs, granted keywords) are cleared from it.

---

## 4. Card Types

### Units
- **Permanent** (stays on board after play).
- Have a **Might** stat (combat power and death threshold).
- Enter the board **exhausted**.
- Can be at a **Base** or **Battlefield**.
- Die when damage ≥ Might (in a Cleanup).
- Have an inherent **Standard Move** action (cost: Exhaust).
- Can have Activated Abilities (usable during controlling player's Main Phase, Open State).

### Gear
- **Permanent** (stays on board).
- Enter play **Ready**.
- Can only be played to the controlling player's **Base** (unless Hidden or attached to a Unit at a Battlefield).
- If unattached at a Battlefield during Cleanup → **Recalled** to Base.
- Can have Activated Abilities.

### Spells
- **Not Permanent**. After resolving, go to Trash.
- By default playable during the controlling player's Main Phase (Neutral Open State).
- **Action** keyword: also playable during Showdowns.
- **Reaction** keyword: also playable during Closed States (on any player's turn).

### Runes
- Kept in the Rune Deck (not the Main Deck).
- **Channeled** (not played) 2 per turn during Channel Phase.
- Produce **Energy** and **Power** (resources).
- Not Permanents, but remain on board until Recycled or removed.
- **Basic Rune abilities:**
  - `[E]: [Reaction] — Add [1]` (tap to add 1 Energy)
  - `Recycle this: [Reaction] — Add [C]` (sacrifice for 1 domain Power)

### Battlefields
- Set up at game start. Cannot be played, killed, or moved.
- Are **Locations** (units move to/from them).
- Can have Passive and Triggered Abilities.
- Controlled by whichever player has Units there (determined through Showdowns/Combat).

### Legends
- In Legend Zone at all times. Cannot leave.
- Not Permanents.
- Can have Passive, Triggered, and Activated Abilities.

---

## 5. Resources

### Rune Pool
- Conceptual pool of **Energy** (numeric) and **Power** (domain-specific).
- Resources must be added before spending.
- **Empties** at end of Draw Phase and end of each player's turn.

### Energy
- Domain-neutral. Pays numeric costs on cards.

### Power
- Domain-specific. Pays the domain symbol costs on cards.
- Universal Power `[A]` can pay any domain's Power cost.

### Paying Costs
- Cards have an **Energy Cost** (number) and optional **Power Cost** (domain symbols).
- Cost is determined: base cost → apply modifiers/additional costs → apply discounts.
- Costs cannot be reduced below 0.

---

## 6. Turn Structure

```
START OF TURN
  1. Awaken Phase     → Ready all Game Objects the Turn Player controls
  2. Beginning Phase
       a. Beginning Step  → "At the start of Beginning Phase" effects trigger
       b. Scoring Step    → Turn Player Holds all Battlefields they control (gain 1 pt each)
  3. Channel Phase    → Turn Player channels 2 Runes from their Rune Deck
  4. Draw Phase       → Turn Player draws 1 card; Rune Pools empty

MAIN PHASE (open-ended)
  - Turn Player has Priority in Neutral Open State
  - May take any Discretionary Actions: play cards, activate abilities, Standard Move units
  - Showdowns and Combats occur as a result of unit movement
  - Player ends their Main Phase when they choose to

END OF TURN
  5. Ending Phase
       a. Ending Step     → "At the end of the turn" effects trigger
       b. Expiration Step → Heal all Units; expire all "this turn" effects; Rune Pool empties
  6. Next player becomes Turn Player
```

---

## 7. Turn States

| State | Definition |
|---|---|
| **Neutral Open** | No Showdown/Combat in progress, no Chain. Default Main Phase state. Turn Player has Priority. Only Turn Player can play cards/abilities (unless specified otherwise). |
| **Neutral Closed** | No Showdown/Combat, but a Chain exists. Only Reaction cards/abilities can be played. |
| **Showdown Open** | Showdown or Combat in progress, no Chain. Player with Focus may play Action/Reaction cards. |
| **Showdown Closed** | Showdown or Combat in progress, Chain exists. Only Reaction cards/abilities. |

**Priority:** Right to take Discretionary Actions. Only 1 player has it at a time.  
**Focus:** Right to act during Showdown Open states. Passes around players in turn order.

---

## 8. The Chain (Stack)

- Created whenever a card is played or an ability is activated.
- Items resolve **last in, first out** (like a stack).
- **Finalize → Execute → Pass → Resolve** (FEPR) process.
- While the Chain exists, state is **Closed** (only Reactions can be added).
- All players pass Priority in sequence → top item resolves.

**Playing a Card steps:**
1. Remove card from zone, place on Chain (Pending). State becomes Closed.
2. Make choices (targets, modes, destinations).
3. Determine Total Cost (base cost ± modifiers ± additional costs ± discounts).
4. Pay costs.
5. Check legality (targets still valid? timing legal?).
6. Finalize: card is placed, enters board (Permanent) or becomes a Chain Item (Spell).

---

## 9. Movement

- Units use the **Standard Move** (Discretionary Action, cost: Exhaust the unit).
- A unit can move from **Base → Battlefield** or **Battlefield → Base**.
- Units with **Ganking** can also move **Battlefield → Battlefield**.
- Multiple units can move simultaneously to the same destination.
- Units cannot move to a Battlefield already occupied by units from 2 other players.
- After a move, a **Cleanup** is performed.

**Contested status:** Applied to a Battlefield when a unit moves there and that unit's controller does not currently control it. This triggers a Showdown (or Combat).

---

## 10. Battlefield Control

- A Battlefield is **Controlled** by a player or **Uncontrolled**.
- Control requires having Units there after a Showdown/Combat resolves.
- If a player has no Units at a Battlefield during an Open State, they lose Control in the next Cleanup.
- While Combat or Showdown is ongoing at a Battlefield, Control cannot change until those steps instruct it.

---

## 11. Showdowns

A **Showdown** is a structured window where players alternate playing Action/Reaction cards.

**When triggered:**
- A unit moves to an **empty, uncontrolled** Battlefield → Non-Combat Showdown.
- Units from two opposing players meet at the same Battlefield → Combat Showdown (Combat begins).

**Showdown flow:**
1. Player who applied Contested gains **Focus**.
2. Players alternate with Focus: play a card (Action/Reaction) or **Pass**.
3. When all players Pass in sequence → Showdown closes.
4. **Non-Combat Showdown result:** if one player's units remain → they establish Control (Conquer if new).
5. **Combat Showdown:** proceed to Combat Damage Step.

---

## 12. Combat

Combat occurs when Units from two opposing players are at the same Battlefield.

### Steps of Combat

**Step 1: Combat Showdown**
- Player who moved in = **Attacker** (gains Focus).
- Player already there = **Defender**.
- Units at the Battlefield gain Attacker/Defender designations.
- Attack Triggers and Defend Triggers fire.
- Players play Action/Reaction cards in alternating Focus.
- When all Pass → Combat Damage Step.

**Step 2: Combat Damage**
- Only fires if both Attacker and Defender units remain.
- Sum all Attacker Might; sum all Defender Might.
- Starting with Attacker: assign damage equal to their total Might across enemy units.
  - Must assign **lethal damage** (damage ≥ unit's Might) to one unit before assigning any to another.
  - **Tank** units must be assigned lethal damage first.
  - **Stunned** units do not contribute their Might to the damage pool.
- Deal all assigned damage simultaneously.

**Step 3: Resolution (Combat Cleanup)**
- Heal all Units.
- Recall Attacker units to their Base if Defenders are still present.
- Check win/loss:
  - **Attacker wins** → only Attacker units remain → establish Control (Conquer).
  - **Defender wins** → only Defender units remain → Defender keeps/establishes Control.
  - **No result** (both or neither have units) → if both remain, Combat is staged again.
- Remove Attacker/Defender designations.
- Expire "this combat" effects.

---

## 13. Scoring & Winning

### Scoring methods

| Method | When |
|---|---|
| **Hold** | During the **Beginning Phase Scoring Step**, the Turn Player gains 1 point per Battlefield they currently control. |
| **Conquer** | When a player gains Control of a Battlefield they haven't scored this turn. |

- A player may score each Battlefield at most **once per turn** (combining Hold + Conquer).
- Hold always awards the point.
- **Conquer + Winning Point rule:** If a player is 1 point away from victory and scores via Conquer, they only gain the Winning Point if they have scored **every Battlefield** this turn; otherwise, they draw a card instead.

### Winning
- **Victory Score (1v1): 8 points.**
- Win condition checked on every Cleanup: player with ≥ Victory Score points AND more points than every opponent wins immediately.

### Burn Out
- If a player must draw but their deck is empty → shuffle Trash into deck → **an opponent gains 1 point** → complete the draw.
- Points gained after the first Burn Out in a sequence cannot be prevented.

---

## 14. Damage & Death

- Damage is tracked per Unit (a temporary value).
- A Unit is **killed** (sent to Trash) during a Cleanup when damage ≥ Might.
- Units with **Deathknell** trigger their effect before being moved to Trash.
- Damage is **healed** at:
  - End of each player's turn (Expiration Step).
  - After Combat (Combat Cleanup).
- **Stun:** A stunned unit does not contribute Might in Combat Damage Step. Stun clears at start of next Ending Step.

---

## 15. Key Keywords (for initial implementation)

| Keyword | Type | Effect |
|---|---|---|
| **Action** | Permissive | Card/ability can be played during Showdowns. |
| **Reaction** | Permissive | Card/ability can be played during Closed States (any turn). |
| **Accelerate** | Optional Cost | Pay `[1] + 1 Power` when playing the unit to have it enter Ready instead of Exhausted. |
| **Assault [X]** | Passive | While attacking, unit has +X Might. |
| **Shield [X]** | Passive | While defending, unit has +X Might. |
| **Tank** | Passive | Must be assigned lethal combat damage before other friendly units (without Tank). |
| **Ganking** | Passive | Unit may Standard Move from Battlefield to Battlefield. |
| **Deflect [X]** | Passive | Enemy spells/abilities that target this cost X more Power. |
| **Deathknell** | Triggered | "When I die, [Effect]." Triggers before being moved to Trash. |
| **Hidden** | Discretionary | Pay `[A]` to place face-down at a controlled Battlefield. Next turn: can play it for free with Reaction timing. |
| **Legion** | Dependent | Ability is active only if the controller played another card this turn. |
| **Temporary** | Triggered | "At the start of my controller's Beginning Phase (before scoring), kill this." |
| **Vision** | Triggered | "When played, look at the top card of your Main Deck. You may Recycle it." |
| **Equip [Cost]** | Activated | `[Cost]: Attach this Gear to a friendly Unit.` |

---

## 16. Buffs

- A **Buff Counter** on a Unit grants **+1 Might**.
- Max **1 Buff** per Unit at a time.
- Buffs can be **spent** (removed) to pay certain costs.
- Cleared when the Unit leaves the board.

---

## 17. Cleanups (State Transitions)

A Cleanup is triggered automatically after most game events (moves, state changes, cards entering/leaving the board, etc.). During a Cleanup:

1. Check win condition (points ≥ Victory Score and more than any opponent → player wins).
2. Assign/Remove Attacker and Defender designations.
3. Handle outstanding board state:
   - a. Deathknell abilities of units with lethal damage trigger.
   - b. Units with lethal damage are killed → sent to Trash.
4. Battlefields with no units in an Open State become **Uncontrolled**.
5. Recall unattached Gear at Battlefields to Base.
6. Mark Showdowns as Staged where Contested was applied.
7. Mark Combat as Staged where Contested was applied and opposing Units are both present.
8. If Neutral Open: Turn Player chooses a Staged Showdown or Combat to begin.

---

## 18. Actions Summary

| Action | Type | Notes |
|---|---|---|
| **Draw** | Limited | Draw Step gives 1; effects can grant more. Burn Out if deck empty. |
| **Exhaust** | Limited (cost) | Rotate card sideways. Can't exhaust an already-exhausted permanent. |
| **Ready** | Limited | Rotate card upright. Happens automatically in Awaken Phase. |
| **Channel** | Limited | Take top 2 Runes from Rune Deck → place on board (Ready). |
| **Standard Move** | Discretionary | Exhaust a Unit to move it Base↔Battlefield (or BF↔BF with Ganking). |
| **Play** | Discretionary | Play a card from hand or Champion Zone (pay costs, follow chain). |
| **Recycle** | Limited | Put card(s) on bottom of their deck. Multiple simultaneously → random order (Main), chosen order (Rune). |
| **Kill** | Limited | Move a Permanent from board to Trash. |
| **Discard** | Limited | Move cards from Hand to Trash without *playing* the card. **`on_discard` triggered abilities** on the discarded card still fire (e.g. Flame Chompers, Scrapheap). |
| **Banish** | Limited | Move card to Banishment zone. |
| **Stun** | Limited | Mark unit Stunned (loses combat Might contribution; clears next Ending Step). |
| **Heal** | Limited | Clear damage from Units. |
| **Buff** | Limited | Place a Buff Counter on a Unit (max 1). |
| **Hide** | Discretionary | Place card face-down at a controlled Battlefield (requires Hidden keyword). |
| **Counter** | Limited | Negate a card or ability on the Chain. Costs already paid are not refunded. |

---

## 19. Player Interaction Model — Command Console

All player input is handled through a **text command console** shared by both human and AI players. There is no drag-and-drop, no clickable buttons for game actions, and no context menus. Every game action is expressed as a typed command string.

This design means the game engine sees no difference between a human typing a command and an AI emitting one — both feed into the same command parser.

---

### 19.1 Console Layout

The console sits at the bottom of the screen as a persistent text input field + scrollable output log. Structure:

```
┌─────────────────────────────────────────────────────────┐
│  [Game Board — zones, cards, state display]             │
├─────────────────────────────────────────────────────────┤
│  OUTPUT LOG (scrollable, newest at bottom)              │
│  > [P1] Moved Noxus Hopeful to Battlefield A            │
│  > Combat staged at Battlefield A                       │
│  > [P2] Passed focus                                    │
│  > Combat damage resolved. Noxus Hopeful killed.        │
│  > P1 scored 1 point (Conquer). Score: P1=3, P2=2       │
├─────────────────────────────────────────────────────────┤
│  [P1] > _                          [Tab: autocomplete]  │
└─────────────────────────────────────────────────────────┘
```

- The **output log** is the game's source of truth for what has happened. All state changes, errors, and prompts are printed here.
- The **input field** accepts commands from the active player (human or AI).
- Commands are **case-insensitive** and use a consistent verb-first structure.
- The game engine only accepts input from the player who currently has **Priority** or **Focus** (or is being prompted for a choice). All other input is rejected with an error message.

---

### 19.2 Command Syntax

All commands follow the pattern:

```
<verb> [target] [options]
```

Arguments are space-separated. Targets are identified by their **instance ID** as printed in the output log. Instance IDs are the kebab-case card name, with `-2`, `-3`, etc. appended when multiple copies of the same card are present. Runes are referenced by index (`rune-0`, `rune-1`, ...).

```
move noxus-hopeful to battlefield-a
move noxus-hopeful noxus-hopeful-2 to battlefield-a
play void-seeker target iron-juggernaut
tap rune-0
recycle rune-2
```

The output log always prints the current instance IDs of cards so players know exactly what to type. Use the `hand`, `board`, or `zones` commands to list them at any time.

---

### 19.3 Command Reference

#### Setup & Mulligan

| Command | Example | Description |
|---|---|---|
| `mulligan <id> [id]` | `mulligan noxus-hopeful void-seeker` | Set aside 1–2 cards by instance ID for the mulligan |
| `mulligan keep` | `mulligan keep` | Keep current hand (skip mulligan) |

#### Turn & Priority

| Command | Example | Description |
|---|---|---|
| `pass` | `pass` | Pass Priority (during Chain) or Focus (during Showdown), or end Main Phase |
| `end turn` | `end turn` | Explicitly signal end of Main Phase and pass turn |

#### Resources

| Command | Example | Description |
|---|---|---|
| `tap rune-<n>` | `tap rune-0` | Exhaust the Nth channeled rune to add 1 Energy to Rune Pool |
| `recycle rune-<n>` | `recycle rune-2` | Recycle the Nth channeled rune to add 1 Power of its domain to Rune Pool |

#### Playing Cards

| Command | Example | Description |
|---|---|---|
| `play <id>` | `play noxus-hopeful` | Play a card from hand (unit goes to Base by default) |
| `play <id> to <location>` | `play noxus-hopeful to battlefield-a` | Play a unit to a specific location |
| `play <id> target <id>` | `play void-seeker target iron-juggernaut` | Play a spell targeting a specific permanent |
| `play <id> from champion` | `play jinx-rebel from champion` | Play the Chosen Champion from the Champion Zone |
| `play <id> from hidden` | `play void-seeker from hidden` | Play a face-down Hidden card at its Battlefield |

#### Movement

| Command | Example | Description |
|---|---|---|
| `move <id> to <location>` | `move noxus-hopeful to battlefield-a` | Standard Move a unit (costs Exhaust). Location: `base`, `battlefield-a`, `battlefield-b` |
| `move <id> <id> ... to <location>` | `move noxus-hopeful noxus-hopeful-2 to battlefield-a` | Move multiple units to the same destination simultaneously |

#### Abilities

| Command | Example | Description |
|---|---|---|
| `use <card-id>` | `use iron-ballista` | Activate the card's only Activated Ability |
| `use <card-id> target <id>` | `use iron-ballista target noxus-hopeful` | Activate an Activated Ability with a target |

#### Showdown / Chain Responses

| Command | Example | Description |
|---|---|---|
| `pass` | `pass` | Pass Focus or Priority |
| `react <id> [target <id>]` | `react challenge target noxus-hopeful` | Play a Reaction card onto the Chain |

#### Combat Damage Assignment

| Command | Example | Description |
|---|---|---|
| `assign <amount> to <id>` | `assign 3 to iron-juggernaut` | Assign N damage to a unit during the Combat Damage step |
| `assign done` | `assign done` | Confirm damage assignment is complete |

#### Choices (prompted by the engine)

When the engine requires a choice (e.g. choosing a target on resolution, picking a mode), it prints a prompt to the log:

```
[PROMPT] Choose a unit to kill (use: choose <id>):
```

| Command | Example | Description |
|---|---|---|
| `choose <id>` | `choose noxus-hopeful` | Respond to an engine-prompted choice (target, hand card to discard, etc.) |
| `choose yes` / `choose no` | `choose yes` | Accept or decline an optional ability prompt |
| `choose none` | `choose none` | Decline an optional choice (not valid for mandatory discards) |

Discard prompts appear when an effect or cost requires discarding from hand:

```
[PROMPT] Choose a card to discard (1 remaining) (use: choose <id>)
```

Multi-card discards (e.g. Jinx) prompt sequentially until all required discards are chosen.

#### Information

| Command | Description |
|---|---|
| `hand` | Print contents of own hand to the log |
| `board` | Print full board state to the log |
| `card <card_id>` | Print full details (stats, abilities, keywords) of a card |
| `chain` | Print current Chain contents |
| `score` | Print current scores |
| `pool` | Print current Rune Pool (energy + power available) |
| `zones` | Print a summary of all zones and their card counts |
| `help` | Print available commands for the current game state |

---

### 19.4 Engine Feedback & Errors

All engine responses are printed to the output log:

| Prefix | Meaning |
|---|---|
| `>` | Normal game event or state change |
| `[PROMPT]` | Engine is waiting for a specific choice from a player |
| `[ERROR]` | Command was rejected — reason follows |
| `[INFO]` | Informational message (card details, zone contents, etc.) |
| `[P1]` / `[P2]` | Indicates which player issued the preceding command |

Examples:
```
[ERROR] Cannot play Void Seeker: insufficient energy (need 4, have 2)
[ERROR] Not your turn to act — waiting for P2 to respond
[PROMPT] Choose a Battlefield to begin the Showdown at (use: choose battlefield-a or choose battlefield-b):
```

---

### 19.5 AI Player Interface

An AI player connects to the same command interface as a human. From the engine's perspective, an AI player is simply an agent that:

1. Reads the output log (or queries game state via the `board`, `hand`, `chain`, etc. commands).
2. Emits a valid command string on its turn.
3. Receives the same feedback as a human player.

The AI does **not** get a privileged API — it must issue the same text commands. This keeps the human and AI interaction paths identical and makes it straightforward to swap one for the other.

AI command injection is handled by the `AIPlayer` node, which calls `GameController.submit_command()` directly, bypassing the text input field but going through the same validation path as the console.

---

### 19.6 Command Parsing Architecture

```
TextInput / AIPlayer
        │
        ▼
  GameController.submit_command()
  - Tokenizes the command string
  - Maps verb → _cmd_* handler
  - Validates current game state allows this action
  - Validates the acting player has Priority / Focus
  - Executes the action, updates game state
  - Triggers Cleanups as needed
        │
        ▼
  Processors (ChainProcessor, CombatProcessor, …)
  AbilityResolver / TriggerDispatcher
        │
        ▼
  OutputLog.gd
  - Prints all state changes, errors, and prompts
```

---

## 20. Modes of Play (1v1 — Primary Implementation Target)

**1v1 Duel:**
- 2 players, no teams.
- **Victory Score: 8** points.
- **2 Battlefields** (each player brings 3; one is randomly chosen per player; both chosen Battlefields are placed).
- Player going second: channels 1 extra Rune on first Channel Phase.
- Format: Best of 1.
