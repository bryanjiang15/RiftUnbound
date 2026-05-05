# Game Design Document
## Async Champion TCG — Working Title TBD

---

## Overview

An asynchronous trading card game where players build a champion roster and equip them with items from a pre-built deck, then fight automatically against "ghosts" — snapshots of other real players' boards from past runs. The goal is to survive as many rounds as possible in a single run.

The game removes the stress and time pressure of synchronous play while preserving the strategic depth of deck building, itemization, and board planning.

**Core inspirations:** The Bazaar (ghost system), TFT (round structure, health system), MTG (color identity), Backpack Battles (item-focused building).

---

## The Run Structure

A run is a series of rounds. Each round the player fights a ghost opponent. The run ends when the player's health reaches zero.

### Round Flow

1. **Planning phase** — the player equips items to their champions, levels up champions, and positions them on the grid.
2. **Combat phase** — combat resolves automatically and deterministically. No player input during combat.
3. **Result** — the player wins the round by killing all opponent champions, or loses and takes health damage.
4. **Repeat** — the next round begins with a new ghost opponent.

### Health System

- The player starts a run with a fixed health total (exact value TBD).
- Losing a round deals damage to the player's health based on the number and strength of surviving enemy champions.
- Winning a round deals no damage to the player.
- When the player's health reaches zero, the run ends.
- There is no health recovery between rounds (TBD — a limited healing mechanic may be added later).

---

## The Ghost System

Ghosts are snapshots of real players' boards captured at the equivalent round number during their own past runs. They are selected randomly from a pool of players who reached the same round.

### Key properties

- Ghosts do not recur. Each round a different ghost is drawn.
- The ghost's board is frozen — it does not adapt between rounds.
- The player sees the ghost's **main champion identity** (name and color) before locking their board, giving partial information for strategic decisions.
- Ghost difficulty is stage-matched: a player in round 3 faces ghosts captured at round 3 of other runs.

### Ghost pool

Every completed round a player plays becomes a ghost snapshot that enters the pool for others to face. A player's skill is expressed not just in surviving their own run but in building a board strong enough to defeat others who face it.

---

## Champions

Champions are the central units of the game. They have health, damage, and unique abilities. They are the only combat units on the board (items may produce minor units, but these are secondary and not always present).

### Champion count — 1 to 3

The player starts a run with one chosen champion and may acquire up to two additional champions during the run, for a maximum of three.

**One champion (superboss)**
- All item slots and level-up investment concentrated in one champion.
- Higher individual health and damage scaling.
- One target for the opponent to kill — high risk, high reward.

**Two or three champions (synergy)**
- Item slots and stats spread across multiple champions.
- Champions of the same or allied colors gain synergy bonuses when fielded together.
- Multiple targets make the board harder to shut down, but each champion is individually weaker.

This is a core strategic fork that defines run identity. Neither option is strictly better.

### Champion leveling

Champions grow stronger by surviving rounds. Each round a champion survives, they gain a level that increases their base stats. The exact stat growth per level and the method for distributing level-up bonuses are **TBD**.

### Champion abilities

Each champion has a unique ability tied to their color identity. Abilities are **TBD** in detail but will reflect their color's playstyle (see Color System below).

---

## The Color System

Champions and items belong to a color that defines their playstyle and mechanical identity. Colors function similarly to MTG's color pie — each color has strengths, weaknesses, and a distinct feel.

### Color design goals

- Players understand a champion's rough strategy from its color alone.
- Same-color item-to-champion matching provides a bonus effect (affinity), but does not lock out off-color items.
- Two same-color or allied-color champions on the same board unlock a **color synergy ability** unique to that pairing.

### Specific colors

The number of colors and their exact identities are **TBD**. Working directions:

| Color | Playstyle | Mechanical theme |
|---|---|---|
| TBD (Aggro) | Fast, high damage | Burst, speed, low health |
| TBD (Control) | Reactive, defensive | Debuffs, damage reduction, counters |
| TBD (Sustain) | Attrition, healing | Health regeneration, shields |
| TBD (Burst/Combo) | Setup and payoff | Synergy triggers, combo chains |

Exact color names, count, and ally-enemy relationships are to be designed.

---

## Items and the Deck

The pre-built deck is the primary expression of player skill and identity outside of a session. It is built before the run begins.

### What items do

- Grant stat bonuses (health, damage, ability power, speed).
- Add passive effects (lifesteal, armor, on-hit triggers).
- Some items produce minor combat units that act as shields or minor damage dealers — these are incidental to the main champion fight, not the focus.
- Items may combine or upgrade into stronger versions (crafting system **TBD**).

### Color affinity

Equipping a same-color item to a same-color champion activates a bonus effect on top of the item's base stats. Off-color items are still valid but do not trigger the bonus.

### Item slots

Each champion has a limited number of item slots (exact number **TBD**). Positioning items within those slots may matter depending on the final item design.

---

## The Grid

Combat takes place on a grid (exact dimensions **TBD**, TFT-style hex or square grid). Players place their champions on their half of the grid during the planning phase.

### Positioning as skill

Grid placement is a meaningful decision:

- Frontline positions take damage first and protect backline champions.
- Champion abilities may have directional or proximity effects that reward specific placements.
- The opponent's main champion identity is visible before placement, allowing informed positioning decisions.

### Champion aura zones (proposed)

Champions may passively buff allied units within a radius of tiles around them. This makes champion placement a strategic trade-off: pushing a champion forward increases aura coverage but increases their exposure. This feature is **proposed but not finalized**.

---

## What Is Missing / TBD

The following systems are acknowledged as necessary but not yet designed:

### Currency and economy system
There is currently no defined resource for acquiring items and additional champions during a run. This is the most critical missing system. Needs to define:
- What the resource is (gold, energy, essence, etc.)
- How it is earned each round (flat amount, win bonus, scaling)
- Whether saving resources earns interest or a bonus (risk-reward tension)
- How items are offered (shop, draft, direct draw from deck)

### Specific color identities
The number of colors, their names, their mechanical identities, and their ally-enemy relationships are not designed.

### Champion ability design
Individual champion abilities are not designed. The framework (color-tied, unique per champion) is defined but no specific abilities exist yet.

### Champion acquisition mid-run
How and when the player obtains their second and third champion is not defined. Candidates: shop purchase, round reward, special event.

### Item crafting and combining
Whether items can be combined into stronger versions (like TFT's item combining or Backpack Battles' crafting) is not designed.

### Stat values and balance
No specific numbers exist yet — champion health, damage, item stat values, health damage per lost round, starting player health, etc.

### Healing between rounds
Whether and how the player recovers health during a run is undecided. A conditional healing mechanic (e.g. win streaks restore some health) was discussed but not finalized.

### Randomness modifiers (locations)
A location or environmental modifier system (similar to Marvel Snap locations) was discussed as a source of in-session variability. Not yet integrated into the core design.

### Deck building rules
Minimum and maximum deck size, rarity restrictions, duplicate limits, and color restrictions (if any) for deck construction are not defined.

---

## Design Principles (Reference)

These are the guiding goals the design is built around:

- **Remove toxicity and time pressure** — no synchronous waiting, no real-time opponent reactions.
- **Preserve strategic depth** — deck building, itemization, positioning, and metagame reading should all reward mastery.
- **The ghost system carries the social layer** — players compete indirectly. Your board becoming a strong ghost is a form of winning even after your run ends.
- **Randomness is input, not output** — random elements (ghost draw, item shop, locations) occur before the player commits their board. Combat resolves deterministically.
- **The 1-vs-3 champion decision is the game's core identity** — this fork defines playstyle more than any other single decision.
