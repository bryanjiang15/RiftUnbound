# Implementation Plan — Async Champion TCG

This document maps the current Godot template to the [game design document](game-design-document.md), proposes systems to build in phases, and lists **design decisions that must be clarified** before or alongside implementation.

---

## 1. Current template vs. target game

### What exists today

| Area | Implementation |
|------|----------------|
| **Core loop** | Synchronous two-player TCG: alternating turns, phases (`Start` → `Main` → `Combat` → `End`), stack resolution, priority passing (`GameState`, `PlayerState`). |
| **Cards** | `CardData`: cost, power, defense, effect hooks (`Effect`, `StaticEffect`), zones (hand, field, grave, banish, deck). |
| **Opponent** | `FreeOpponent`: connects to priority and auto-emits `PassAction` — suitable only as a stub AI that never plays cards. |
| **Meta** | `PlayerProfile`, `Deck`, collection/deck UI scaffolding (`DeckController`, collection scenes). |
| **Combat** | Phases exist but **autoresolve combat is not implemented**; no grid, no deterministic tick/TFT-style resolution. |

### Mismatch with the GDD

The design calls for:

- **Run-based progression** (player health across rounds, lose-on-zero), not alternating-turn matches until someone “wins” by an undefined TCG rule (`player.won` is unused in the simple flow).
- **Planning phase → deterministic combat → round result**, not continuous priority/stack play during combat.
- **Champions on a grid**, items equipped to champions, **1–3 champions**, leveling — not a flat “field” of generic cards with mana costs each turn.
- **Ghost opponents** (snapshots + matchmaking by round), **economy between rounds**, **deck-as-item-source** — none of this exists in code.

**Strategic implication:** You will either **replace** large parts of `GameState`’s turn/priority model for the run mode, or **fork** a separate `RunState` / `RoundController` that only reuses data types (`CardData` → evolve into items/champions) and UI patterns. The existing stack-based phase loop is a poor fit for “no input during combat” unless combat is isolated as a pure function after planning locks.

---

## 2. Recommended implementation phases

Phases are ordered so each delivers a testable slice. Dependencies are noted inline.

### Phase A — Design locks & domain model (foundation)

**Goal:** Stop encoding TCG assumptions into resources before they become migration debt.

**Features / work**

- **Domain terminology in code:** Introduce distinct concepts (even as thin Resources) for `Champion`, `Item`, `GhostBoard`, `RunSnapshot`, separate from generic “card” where behavior diverges — or explicitly extend `CardData` with `kind` enum and documented invariants.
- **Stat schema:** Single source of truth for combat stats (health, attack, ability power, speed, armor, etc.) — align names with whatever combat math you choose in Phase D.
- **Save-safe identifiers:** Ghost snapshots and persistence need stable IDs (`CardData.instance_id` pattern can extend to champions/items-in-run).

**Design clarifications required:** Economy currency, starting player health, grid size, slot counts (see §4).

---

### Phase B — Run shell and round lifecycle

**Goal:** Implement “survive N rounds; player health persists; win/lose round” without full combat or ghosts.

**Features / work**

- **Run state:** Starting health, current round index, optional streak counters, terminal condition (health ≤ 0).
- **Round state machine:** `Planning` → `CombatResolve` → `RoundResult` → advance round or end run.
- **Round outcome:** Win = no damage to player health; lose = damage from formula (placeholder: `f(surviving_enemy_value)` until balance exists).
- **UI:** Minimal run HUD (health, round #, phase label). Wire debug buttons to advance phases.

**Reuse:** `GameParams` can evolve into `RunParams` (starting health, damage formula coefficients).

**Design clarifications:** Damage-on-loss formula; whether any healing exists between rounds.

---

### Phase C — Planning: grid, champions, items (local-first)

**Goal:** Player can position **their** champions and assign items from **their deck** before combat, without network ghosts.

**Features / work**

- **Grid representation:** Data structure for cells, ownership (player half vs opponent half), occupancy, optional line-of-sight / adjacency for future abilities.
- **Champion instances:** Per-run stats, level, occupied cells, item slots, references to `Champion` definitions.
- **Item assignment:** Drag-from-deck or shop placeholder → champion slot; enforce slot limits; color affinity hook (can stub bonus as +0 until colors are defined).
- **Lock planning:** Immutable snapshot of “board + loadouts” passed into combat resolver.

**Reuse:** Board UI (`BoardUI`) as starting point for grid visualization; collection/deck for loading definitions.

**Design clarifications:** Exact grid dimensions and shape (hex vs square); item slots per champion; whether slot index matters; how many champions at run start; how 2nd/3rd champion is unlocked.

---

### Phase D — Combat: deterministic autobattle core

**Goal:** Given two locked boards + definitions, produce a reproducible outcome (no priority/stack).

**Features / work**

- **Combat model:** Turn order or simultaneous tick (must be fixed in design), targeting rules, death/removal, ability triggers ordering — **deterministic** given fixed RNG seed for any in-combat randomness (ideally: **no randomness in combat** per GDD principle).
- **Unit controller:** Champions as units; optional **minions** from items as secondary units with simplified AI.
- **Ability execution:** Data-driven or scripted hooks (`Ability`) tied to champion/color; start with 1–2 placeholder abilities.
- **Telemetry:** Combat log (events list) for UI replay and debugging ghost fairness.

**Reuse:** `Effect` / `StaticEffect` only if you unify them with combat events; otherwise avoid forcing TCG “stack” semantics into autobattle.

**Design clarifications:** Full ability list per champion; color bonuses; aura zones (yes/no and radius); whether positioning affects targeting beyond front/back.

---

### Phase E — Ghost system (offline → online)

**Goal:** Opponent board is a **snapshot** at round R; player sees partial info before planning.

**Features / work**

- **Snapshot format:** Serialize planning snapshot + metadata (round number, main champion identity, optional MMR band).
- **Pool / selection:** Seed with AI or developer snapshots; later, queue player snapshots by round index. “No duplicate ghost per run” rule.
- **Reveal rules:** UI shows **main champion identity** (name/color) during planning; hide rest until combat if desired by design.
- **Privacy / consent:** If snapshots include loadouts from real players, define retention and opt-in (product decision).

**Design clarifications:** Exact reveal tier list; pool matching (skill brackets or purely round-based).

---

### Phase F — Economy and mid-run progression

**Goal:** Supports acquiring items and extra champions during a run per GDD gap analysis.

**Features / work**

- **Currency:** Earn/spend pipeline tied to round transitions (and optionally win bonuses).
- **Offers:** Shop refresh, draft packs from deck, or combination — driven by clarified economy.
- **Interest / banked currency:** If design includes TFT-like interest, implement storage and UI risk signaling.

**Design clarifications:** This is the **largest GDD gap** — cannot finalize implementation without resource loop decisions (see §4.1).

---

### Phase G — Deck building & metagame rules

**Goal:** Enforce deck construction and persist player collections.

**Features / work**

- **Rules engine:** Min/max deck size, duplicate limits, color/rarity constraints.
- **Validation UI:** Illegal decks blocked or warned in collection manager.
- **Progression:** Unlock cards/champions (out of scope unless product specifies).

**Design clarifications:** Full deck ruleset (§4.7).

---

### Phase H — Polish, async UX, and optional systems

**Features / work**

- **Async UX:** No waiting for live opponent; clear run summary; ghost attribution (“You lost to X’s snapshot”).
- **Locations / modifiers:** Rule layer applied at round start (Marvel Snap–style) — optional module once core loop is fun.
- **Item crafting:** Only if design confirms combining paths.

---

## 3. Features to defer or retire from the template

| Template piece | Recommendation |
|------------------|----------------|
| `GameState.take_turn` stack loop | **Do not extend** for run mode; replace with round controller + isolated combat resolver for clarity. |
| Mana per turn | **Not in GDD** for planning/autobattle as described; repurpose or remove for run mode to avoid confusion. |
| `FreeOpponent` | Replace with **ghost loader** or deterministic AI that consumes snapshots, not priority passes. |
| Win condition `player.won` | Replace with **run health / round win** semantics. |

Keep **CardData/Deck** only where they still mean “item definitions” or shared content pipeline; rename when ambiguity hurts onboarding.

---

## 4. Design decisions requiring clarification

Grouped by GDD section. Items marked **blocking** gates accurate implementation of dependent phases.

### 4.1 Economy (blocking Phase F and parts of C)

- Resource name and integer vs fractional rules.
- Income per round: flat, win bonus, loss consolation, scaling by round.
- Interest or reward for saving currency.
- How offers are generated: full deck draft, shop table, hybrid; reroll costs.
- How **second and third champions** enter the run (shop, milestone round, quest).

### 4.2 Run parameters (blocking Phase B)

- Starting player health.
- Damage on loss: function of enemy survivors’ count/stats/tier.
- Healing between rounds: none vs conditional (e.g. win streak).

### 4.3 Grid and positioning (blocking Phase C/D)

- Dimensions; hex vs square; how “frontline” is defined mechanically.
- Whether **aura zones** ship in v1 or are cut.

### 4.4 Colors and identities (blocking synergy + affinity)

- Number of colors; names; ally/enemy color pairs.
- Same-board **pair synergy abilities**: scope (one per pair vs per color combo).

### 4.5 Champions (blocking C/D)

- Starting champion pick vs random; roster size for MVP.
- **Leveling:** stat growth per level; manual stat allocation vs automatic.
- Per-champion ability list (even 2–3 per color for prototype).

### 4.6 Items (blocking C/F)

- Slots per champion; whether geometry within slots matters.
- Crafting/combining: yes/no; recipe shape.

### 4.7 Deck building (blocking G)

- Deck size bounds; duplicate limits; color/rarity restrictions.

### 4.8 Ghost / social (blocking E)

- Snapshot fields stored server-side; anonymization; retention.
- Matchmaking: round-only vs MMR-assisted.

### 4.9 Randomness policy (cross-cutting)

- GDD: randomness before commitment, deterministic combat. Clarify **exactly** what is rolled when (shop order, ghost draw, location) and whether a visible **seed** or replay log is required for fairness/debugging.

---

## 5. Suggested next steps (order of operations)

1. **Lock a minimal combat vertical slice:** 1v1 champions, no items, square grid placeholder, deterministic damage — validates Phase D before investing in economy.
2. **Parallel:** Answer §4.2 and §4.3 at stub level so Phase B/C have numeric placeholders.
3. **Economy workshop:** Answer §4.1 before building inventory/champion acquisition UI in earnest.
4. **Replace or isolate** legacy `GameState` turn loop once run shell (`Phase B`) proves stable — avoids maintaining two incompatible rules engines in one class.

---

## 6. Traceability to GDD sections

| GDD topic | Primary implementation phase |
|-----------|------------------------------|
| Run structure & health | B |
| Planning vs combat | B, C, D |
| Ghost system | E |
| Champions & leveling | C, D |
| Color system | C, D, G |
| Items & deck | C, F, G |
| Grid & positioning | C, D |
| Economy gap | F |
| TBD appendix (crafting, locations, healing) | H or parallel spikes |

This plan should be updated when §4 items move from TBD to decided so engineering estimates stay honest.
