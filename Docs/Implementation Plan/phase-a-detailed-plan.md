# Phase A — Detailed plan: design locks & domain model

This document expands [§2 Phase A](../game-implementation-plan.md) in `game-implementation-plan.md`. It lists **domain concepts**, **schemas**, and **deliverables** for the foundation layer, with explicit signals for what is **required for the base game**, what is **still undecided**, and what is **out of scope for the base game** (but may appear as reserved shape).

---

## Legend (read every table)

| Signal | Meaning |
|--------|---------|
| **`BASE-REQ`** | Needed to implement the **minimal base vertical slice** (local run shell, planning lock, deterministic combat without ghosts/economy/complex deck rules — aligned with parent doc §5 step 1). |
| **`BASE-STUB`** | Part of the base path but **safe as a placeholder** (constants, empty arrays, `TODO` hooks) until design locks. |
| **`DEFER`** | **Not required** for the base game; schema may reserve extension points so later phases do not rewrite IDs or stat layout. |
| **`TBD`** | **Design undecided** in the GDD / §4; do **not** bake specifics into code until decided — use stubs or config-driven defaults. |
| **`CLARIFY`** | Parent doc expects an answer **before or alongside** Phase A/B/C work; track owner + target doc when closing. |

---

## Implementation status (codebase)

Last reviewed against `res://Scripts/Domain/` and related migrations.

### Implemented

- [x] **`CombatStats`** — [`Scripts/Domain/CombatStats.gd`](../../Scripts/Domain/CombatStats.gd)
- [x] **`GridCoord`** — square + axial hex shapes, `to_key()` — [`Scripts/Domain/GridCoord.gd`](../../Scripts/Domain/GridCoord.gd)
- [x] **`InstanceIdScope`** — monotonic `int` instance ids — [`Scripts/Domain/InstanceIdScope.gd`](../../Scripts/Domain/InstanceIdScope.gd)
- [x] **`ChampionData`** — separate from `CardData` — [`Scripts/Domain/ChampionData.gd`](../../Scripts/Domain/ChampionData.gd)
- [x] **`ChampionInstance`** — `from_definition()` + stats copy — [`Scripts/Domain/ChampionInstance.gd`](../../Scripts/Domain/ChampionInstance.gd)
- [x] **`CardInstance`** — [`Scripts/Domain/CardInstance.gd`](../../Scripts/Domain/CardInstance.gd)
- [x] **`PlanningSnapshot`** — header + champion arrays + `deployed_allies` + `occupancy` — [`Scripts/Domain/PlanningSnapshot.gd`](../../Scripts/Domain/PlanningSnapshot.gd)
- [x] **`CardData`** — `CardType` + `card_kind` (default `OTHER`) + `definition_id`; legacy runtime fields marked deprecated in comments — [`Scripts/Card/CardData.gd`](../../Scripts/Card/CardData.gd)
- [x] **Deck / player hero migration** — `Deck.hero` and `PlayerState.hero` are `ChampionData`; sample champion asset [`Champions/AzealeaBorealis.tres`](../../Champions/AzealeaBorealis.tres); profile/opponent decks updated ([`Characters/DefaultPlayer.tres`](../../Characters/DefaultPlayer.tres), [`Characters/FreeOpponent.tres`](../../Characters/FreeOpponent.tres))
- [x] **ID policy** — documented in §3.1 below (this file)
- [x] **Glossary ↔ code** — table in §2 below

### Partial / stubs (acceptable for Phase A; tighten when design locks)

- [ ] **`PlanningSnapshot` disk serialization** — `RefCounted` unit rows are in-memory only; `.tres` save/replay pipeline comes with Phase D/E or an explicit serialization pass.
- [ ] **`run_id` population** — field exists; allocator / persistence not wired (Phase B+).
- [ ] **`rng_seed` policy** — still **`TBD`** (parent §4.9); not encoded on snapshot yet.
- [ ] **`occupancy` validation** — dictionary shape is contract-only; no helpers to keep it in sync with champion/ally arrays.
- [ ] **`CardData` content tagging** — most legacy cards remain `card_kind = OTHER`; fill `definition_id` / kinds when content pipeline exists.
- [ ] **`ChampionInstance.level`** — not modeled yet (§4.5 **`TBD`**).
- [ ] **`GhostBoardSnapshot`** — not created (still **`DEFER`** unless you add an empty type early).

### Still needed later (outside this Phase A slice)

- [ ] **Parent plan ADR / changelog line** — record champion vs card split in [`game-implementation-plan.md`](../game-implementation-plan.md) (deliverable §5.4).
- [ ] **Run shell (`RunState`, round machine)** — Phase B; uses `round_index` / `run_id` from snapshot header conceptually.
- [ ] **Grid UI + `BoardLayout`** — Phase C; dimensions / player half still **`CLARIFY`** §4.3.
- [ ] **Combat resolver + tests using `CombatStats`** — Phase D; optional unit test calling `ChampionInstance.from_definition()` not required yet but recommended before combat work grows.
- [ ] **Champion preview in collection/deck UI** — if builders assume a card-shaped hero; new flow should show `ChampionData` (portrait) where relevant.
- [ ] **Retire legacy `CardData` runtime fields** — route TCG/run code through `CardInstance` and remove `instance_id`/`owner`/`controller` from `CardData` when safe.
- [ ] **Explicit “do not extend” list for legacy `GameState`** — paragraph in parent doc or ADR (deliverable §5.6).

---

## 1. What “base game” means here

For Phase A, **base game** means the smallest end-to-end proof described in the parent plan:

- **Run + round lifecycle** (starting health, round index, terminal condition) — implemented in Phase B but **domain IDs and stat shapes** are fixed in Phase A.
- **Planning → locked snapshot → combat resolve** without live opponent input during combat.
- **One champion per side** for the first slice (extra champions, shop, ghosts are **DEFER** unless an ID type is shared).

Anything required only for **ghosts (E)**, **economy (F)**, **full deck rules (G)**, or **locations/crafting (H)** is labeled **`DEFER`** for base-game Phase A work.

---

## 2. Domain model (concepts)

Introduce **named concepts in code** so TCG-only naming does not spread (`CardData` as “everything” is migration debt). Phase A either adds **thin Resources** or **documented `kind` + invariants** on existing types.

| Concept | Description | Phase A action | Base game | Build status |
|---------|-------------|----------------|-----------|--------------|
| **Champion (definition)** | Static roster data: id, display name, ability hooks, base stats, color/identity. | **`ChampionData`** (separate from `CardData`; locked in §3.3). | **BASE-REQ** | **Done** — `ChampionData.gd` |
| **Champion (instance)** | Per-run/per-combat state: level, current stats, grid cell, item refs, instance id. | **`ChampionInstance`** (RefCounted) + `InstanceIdScope`. | **BASE-REQ** | **Partial** — no `level` yet; equipment array exists, unused |
| **Item (definition)** | Deck/equipment card: cost, effects, slot rules — evolution of item-as-card. | **`CardData`** + **`CardType`** / **`card_kind`**. | **BASE-STUB** (items can be **zero** in slice; shape still exists) **`TBD`** slot geometry | **Done** (enum + fields); **Later** — tag content, slot rules |
| **Combat stats** | Single struct for all units in combat math. | **`CombatStats`** used by definitions + instances. | **BASE-REQ** | **Done** — align names with GDD when §4 locks |
| **Planning snapshot** | Immutable input to combat: board occupancy, unit poses, loadouts at lock. | **`PlanningSnapshot`**; deep-copy before combat when mutating. | **BASE-REQ** | **Partial** — skeleton + occupancy map; disk save **Later** |
| **Run / round identifiers** | Correlation for logs, saves, future ghosts. | **`run_id`**, **`round_index`** on snapshot; **`rng_seed`** policy. | **BASE-REQ** (round index); seed **`TBD`** | **Partial** — fields exist; wiring **Phase B+** |
| **Ghost board / opponent snapshot** | Stored opponent planning state + metadata for matchmaking. | **`GhostBoardSnapshot`** type name + fields stubbed; loader empty. | **DEFER** (type stub **BASE-STUB** if you want one serialization path early) | **Not started** |
| **Economy / currency** | Shop, interest, offers. | No types beyond optional **`meta: Dictionary`** on run if needed. | **DEFER** · **`TBD`** §4.1 | **Not started** |
| **Player run health** | Scalar tracking damage across rounds. | Field on future `RunState`; **default numeric placeholder** only. | **BASE-STUB** · **`CLARIFY`** §4.2 starting health | **Not started** (Phase B) |

**Glossary ↔ code (Phase A):**

| Term | Code |
|------|------|
| Champion definition | `ChampionData` |
| Champion runtime | `ChampionInstance` |
| Card definition | `CardData` + `CardType` |
| Card runtime | `CardInstance` |
| Combat numbers | `CombatStats` |
| Cell / coords | `GridCoord` |
| Planning lock | `PlanningSnapshot` |
| Per-run instance ids | `InstanceIdScope` |

---

## 3. Schema (data shapes)

### 3.1 Identifiers (save-safe, network-ready)

| Field | Type (suggested) | Purpose | Base game |
|-------|------------------|---------|-----------|
| `definition_id` | `StringName` or stable string | Content pipeline id for champion/item definitions. | **BASE-REQ** |
| `instance_id` | `int` or `String` (UUID) | Per-run unique unit/stack row; **must** be unique within a `PlanningSnapshot` / combat log. | **BASE-REQ** |
| `run_id` | `String` | Persisted run; **DEFER** full persistence UX but **reserve** in snapshot header. | **BASE-STUB** |

**Rule:** Phase A chooses **one** id style for `instance_id` (monotonic int vs UUID string) and documents it; ghosts and replays depend on it later (**DEFER** consumers).

**Implementation (locked):** `definition_id` is `StringName` on `ChampionData`; `CardData` may use `definition_id` when assigned in content. **`instance_id` is `int`**, allocated per run via `InstanceIdScope` (`Scripts/Domain/InstanceIdScope.gd`): monotonic starting at `1`, suitable for logs and deterministic replay. UUID strings remain an alternative if networking requires global uniqueness without a central allocator.

---

### 3.2 Combat stats (`CombatStats` / `StatBlock`)

Single source of truth for combat math; names align with whatever Phase D implements (**`TBD`** exact list — parent §4.3/§4.5).

| Stat (example names) | Included in v1 struct | Base game | Notes |
|------------------------|----------------------|-----------|--------|
| `max_health`, `current_health` | yes | **BASE-REQ** | |
| `attack` / `power` | yes | **BASE-REQ** | Rename to match GDD once locked **`TBD`** |
| `defense` / `armor` | optional field | **BASE-STUB** | Zero allowed for slice |
| `speed` / `initiative` | optional | **BASE-STUB** | Deterministic tie-break **`TBD`** |
| `ability_power`, `crit`, etc. | optional | **DEFER** or **BASE-STUB** | Add when first ability needs them |

Signal **undecided** design by **keeping fields in a config or enum**, not by scattering magic numbers in scenes.

---

### 3.3 `CardData` evolution (items & kinds)

**Locked implementation:** Champions use **`ChampionData`** (`Scripts/Domain/ChampionData.gd`), not `CardData`. **`CardData`** carries **`CardType`** (`ITEM`, `EQUIPMENT`, `ALLY`, `SPELL`, `OTHER`) via **`card_kind`** (default **`OTHER`** for legacy assets). Optional **`definition_id`** on `CardData` for stable content ids. Traps/locations remain out of scope until listed.

---

### 3.4 Grid / board **schema** (data only)

Phase A does **not** build grid UI (Phase C); it **fixes** how positions are stored so Phase C/D share one model.

| Piece | Suggestion | Base game | Notes |
|-------|------------|-----------|--------|
| `GridCoord` | `(q,r)` for hex **or** `(x,y)` for square | **BASE-REQ** | **`TBD`** hex vs square — implement **both** behind interface **BASE-STUB** or pick square first per parent §5 |
| `BoardLayout` | dimensions, player half vs opponent half | **BASE-STUB** | Dimensions **`CLARIFY`** §4.3 |
| Occupancy map | `Dictionary` / typed map: `coord → instance_id` | **BASE-REQ** for snapshot | |

---

### 3.5 `PlanningSnapshot` (minimum contract)

Serializable bundle passed into combat resolver (Phase D).

| Field (as implemented) | Purpose | Base game | Build status |
|--------------------------|---------|-----------|--------------|
| `schema_version`, `round_index`, `run_id` | Traceability / format evolution | **BASE-STUB** / **BASE-REQ** | **Partial** — `run_id` not assigned yet |
| `player_champions` | `Array[ChampionInstance]` | **BASE-REQ** | **Done** (empty until planning builds instances) |
| `opponent_champions` | Same for local / AI opponent | **BASE-REQ** | **Done** |
| `deployed_allies` | `Array[CardInstance]` on grid (allies) | **BASE-STUB** (later) | **Stub** — array exists, unused |
| `occupancy` | `GridCoord.to_key()` → `{ "kind", "instance_id" }` | **BASE-REQ** | **Done** (contract only; no validator) |
| `locked_at_ms` | Debug timestamp | **BASE-STUB** | **Not started** — use `Time.get_ticks_msec()` when locking is implemented |
| `ghost_source_id`, `mmr_band` | Ghost provenance | **DEFER** | **Not started** |

Opponent for base slice = **local deterministic AI or blank board**, not player ghosts (**DEFER**).

---

## 4. Design locks checklist (from parent Phase A + §4 touchpoints)

Track these in design docs or tickets; Phase A code should **not** hardcode conflicting values.

| Topic | Signal | Owner / note |
|-------|--------|----------------|
| Economy currency & income | **`TBD`** · **`DEFER`** base | §4.1 — blocks Phase F, not Phase A schema beyond extension points |
| Starting player health, damage-on-loss | **`CLARIFY`** · **`TBD`** | §4.2 — stub constants OK for Phase B |
| Grid dimensions, hex vs square, aura v1 | **`CLARIFY`** · **`TBD`** | §4.3 |
| Color count & synergy scope | **`TBD`** · **DEFER** minimal combat | §4.4 — base slice can use one color |
| Champion leveling & ability list size | **`TBD`** | §4.5 |
| Item slots & crafting | **`TBD`** · **DEFER** if no items in slice | §4.6 |
| Deck construction rules | **`TBD`** · **DEFER** base | §4.7 |
| Ghost fields & matchmaking | **`TBD`** · **DEFER** | §4.8 |
| Randomness policy (shop, seed visibility) | **`TBD`** | §4.9 |

---

## 5. Phase A engineering deliverables (concrete)

1. [x] **Glossary ↔ code map** — Table in §2 (and **Implementation status** above).
2. [x] **`CombatStats`** — Implemented; used from `ChampionData` / `ChampionInstance.from_definition()`. [ ] Optional **unit test** still recommended before large combat refactors.
3. [x] **ID policy** — §3.1 in this file (`definition_id`, `instance_id`, snapshot header intent).
4. [ ] **`CardData` / champion split in parent plan** — Add a short paragraph or ADR note to [`game-implementation-plan.md`](../game-implementation-plan.md) pointing at §3.3 here (split is **locked in code** already).
5. [x] **`PlanningSnapshot` skeleton** — In-memory rows; **full serialization** remains [ ] **later** (replay/save).
6. [ ] **Explicit list of template types to stop extending** — Still add a pointer in parent doc §3 or a short ADR (legacy `GameState` / mana); code comment-only is not done yet.

---

## 6. What Phase A explicitly does **not** include

| Excluded | Signal |
|----------|--------|
| Full run state machine (Phase B) | **DEFER** |
| Grid UI, drag-drop items (Phase C) | **DEFER** |
| Combat resolver, abilities (Phase D) | **DEFER** |
| Ghost pool, snapshot upload (Phase E) | **DEFER** |
| Shop, currency pipelines (Phase F) | **DEFER** |
| Deck validation UI (Phase G) | **DEFER** |

---

## 7. Traceability

| Parent section | This doc |
|----------------|----------|
| [game-implementation-plan §2 Phase A](../game-implementation-plan.md) | Sections 2–5 |
| §4 design decisions | Section 4 checklist |
| §5 suggested next steps | Section 1 “base game” + **BASE-*** tags |

Update **Implementation status** when new types land or stubs graduate to full implementations. Update §4 when items move from **`TBD`** to decided — especially **`CombatStats`** field names and **`GridCoord`** default for production — so Phase B/C/D estimates stay accurate.
