# `search_for` Tool Schema — Reference

Status: **implemented (Phase 1–3).** Phase 1 shipped the `PredicateClause` /
`search_for` contract over candidate-line `search_state` snapshots. Phase 2
prefers a live `/engine/search` corpus when Godot's `EngineServer` is pinned,
with the same filter semantics and a fail-safe back to the Phase-1 corpus. Phase
3 uses this contract inside the Reasoner loop.

Companion: `ai_agent/docs/Deliberative_Reasoning_Toolkit.md` (why this tool
exists), `ai_agent/docs/Goal_Oriented_Strategist.md` (the compiler/whitelist this
reuses).

---

## 1. Why a schema at all (design stance)

The Reasoner makes the decisions — but `search_for` is a **tool call**, and tool
calls are structured contracts by definition. Structure here is not distrust of
the model; it is what makes the tool *safe and deterministic*:

- Each clause is evaluated against a candidate line's **post-line state**
(§7) by a **pure function** (reusing `goal_compiler.graded_value`), no second
LLM parse.
- A clause naming an **off-whitelist** metric compiles to a **no-op**, never a
crash or a garbage filter (same guarantee as goals today).
- Free-form natural-language constraints are explicitly rejected: they would
require an LLM to re-interpret them (latency + drift) and lose the no-op
safety. Flexibility comes from **composition + a whitelisted vocabulary**, not
from open text. See Deliberative_Reasoning_Toolkit §"specialized agent".



## 2. Relationship to the current `Goal` schema


|          | Current `Goal` (`schemas.py:349`)                       | This schema                          |
| -------- | ------------------------------------------------------- | ------------------------------------ |
| Shape    | one object, 3 `kind`s flattened into ~7 optional fields | one focused `PredicateClause`        |
| Role     | output that biases the search (overlay)                 | **input** to a search query (filter) |
| Weakness | easy to fill wrong (which fields go with which kind?)   | one kind, required fields explicit   |


**Migration intent:** `PredicateClause` becomes the single predicate *shape*.
`weight_bias` and `card_target` remain separate concerns (they scale terms / name
cards, not predicates) and move out of the overloaded `Goal` object into their own
small types. Net: the "weak AI-made" union goes away.

**Shape is shared; the metric namespace is not.** A `search_for` clause and a
scoring bias-goal have the *same fields* (`metric / target / comparator /
threshold`) but draw `metric` from **different vocabularies**, on purpose:

- **`search_for`** draws from the **concrete-state vocabulary** (§5): absolute,
  human-legible quantities about a specific entity ("vi-1's Might", "opponent's
  hand size"). These are *goals a player would say out loud*.
- **Scoring bias** draws from the scoring-feature whitelist (differentials,
  fragility heuristics) — good for *leaning an evaluator*, useless as an explicit
  goal to reason about ("achieve `control_fragility >= 2`" means nothing).

So the abstract features (`*_fragility`, `*_net`, `*_diff`, `*_margin`,
`hold_income`) are **excluded from `search_for`**. They keep living in the scoring
overlay where they belong.

## 3. `PredicateClause` — the atomic unit

```jsonc
{
  "metric":     "unit_might",       // REQUIRED. one id from §5 (the concrete vocabulary)
  "comparator": ">=",               // REQUIRED. ">=" | "<=" | "==" (synonyms normalized)
  "threshold":  4,                  // REQUIRED. number
  "target":     "vi-1",             // the entity the metric is about. WHAT it names is
                                    //   fixed by the metric (§5):
                                    //     unit metrics        → a unit instance id ("vi-1")
                                    //     battlefield metrics → a battlefield id ("battlefield-b")
                                    //     player metrics      → "me" | "opponent"
                                    //     card metrics        → a card instance id
                                    //     this-turn outcomes  → omitted (always me, this turn)
  "weight":     "high",             // OPTIONAL. low|med|high — importance for ranking
                                    //   and weighted combine; default "med".
  "label":      "vi-survives-big"   // OPTIONAL. human tag echoed in per-clause feedback
}
```

Notes:

- The metric decides what `target` means and whether it's required — the tool
  schema documents this per metric, and validation rejects a unit metric with a
  battlefield target, etc.
- **Owner is baked into the metric name** where an entity has two sides
  (`my_might_on_battlefield` vs `opponent_might_on_battlefield`) so a clause reads
  unambiguously without a separate `side` field.
- Evaluation resolves the metric against the line's **post-line state snapshot**
  (§7): `resolve(snapshot, metric, target)` → value, then
  `graded_value(value, comparator, threshold)` → [0,1].
- **Continuous** metrics (Might, hand size, runes) are **graded** — a line halfway
  to the threshold scores ~0.5, so the tool can report "closest miss" instead of a
  bare "no match". **Boolean** metrics (`unit_alive`, `i_control_battlefield`,
  `card_played`) are exact: 1.0 or 0.0.



## 4. `search_for` — the tool call



### 4.1 Request

```jsonc
{
  "name": "search_for",
  "arguments": {
    "constraints": [ PredicateClause, ... ],   // REQUIRED, 1..6 clauses
    "combine": "all",       // OPTIONAL. how to fold per-clause satisfaction:
                            //   "all"      → min (weakest-link, strict AND)  [default]
                            //   "any"      → max (OR — any clause is enough)
                            //   "weighted" → weight-weighted mean of clauses
    "top_n": 5,             // OPTIONAL. max matching lines to return (default 5)
    "min_satisfaction": 0.0 // OPTIONAL. keep lines with combined satisfaction >
                            //   this cutoff (default 0.0 = any partial progress).
                            //   Set 1.0 to demand fully-satisfied lines only.
  }
}
```

Design points:

- **Compound is the default shape** — a single condition is just a 1-element
`constraints` list. There is no separate scalar-arg form to maintain.
- `combine:"all"` (weakest-link) is the honest default for "achieve A AND B AND
C": a line is only as good as its worst clause.
- Clause count capped (≤6) to avoid multi-objective soup, mirroring the ≤4-goal
cap.



### 4.2 Response

The per-clause breakdown is the load-bearing feature — it tells the model *which*
constraint failed, so the next ReAct round can adapt.

```jsonc
{
  "query": { "constraints": [...], "combine": "all" },   // echo, for the transcript
  "corpus_size": 25,                                      // lines available to filter
  "matches": [
    {
      "line_id": "line-7",
      "moves": ["move vi-1 battlefield-b", "play gust", "end turn"],
      "score": 12.3,                 // engine mechanical score (base profile)
      "satisfaction": 0.75,          // combined [0,1] under `combine`
      "hard_match": false,           // true iff every clause fully satisfied
      "clauses": [
        { "label": "conquer-b",  "metric": "i_control_battlefield", "target": "battlefield-b",
          "value": 1, "satisfaction": 1.0, "met": true },
        { "label": "keep-runes", "metric": "ready_runes", "target": "me",
          "value": 1, "satisfaction": 0.5, "met": false }   // wanted >=2, got 1
      ]
    }
  ],
  "note": "3/25 lines make progress; 0 fully satisfy. Best miss: 'keep-runes' (1 of 2 ready)."
}
```

- **Empty** `matches` **is informative, not an error.** "No line in the corpus
reaches this" is a real answer the model should act on (drop the objective).
- `note` should name the binding constraint when few/none match — that is the
cue that turns a dead end into a refined next query.



## 5. Predicate vocabulary — concrete, entity-scoped conditions

**Design rule:** a `search_for` condition is an **absolute quantity about a
specific entity** — something a player would say out loud as a goal ("get vi-1 to
4 Might", "hold battlefield-b", "empty the opponent's hand"). Never a
differential, a heuristic, or a my-minus-opp margin. Those are for the scoring
overlay (§2), not for goals a reasoner sets and then checks.

Metrics are grouped by the **subject** they attach to. Each row states what
`target` must be. The enum is generated at schema-build time from this registry
(like `goal_vocabulary_block()`), so the tool schema can never drift from it.

### Unit conditions — `target` = a unit instance id (e.g. `vi-1`)
| metric | meaning | kind |
| --- | --- | --- |
| `unit_might` | the unit's Might after the line | continuous |
| `unit_health` | remaining health = Might − damage after the line | continuous |
| `unit_damage` | damage marked on the unit after the line | continuous |
| `unit_alive` | 1 if the unit is still in play after the line, else 0 | boolean |

### Battlefield conditions — `target` = a battlefield id (e.g. `battlefield-b`)
| metric | meaning | kind |
| --- | --- | --- |
| `my_might_on_battlefield` | total Might of **my** units there after the line | continuous |
| `opponent_might_on_battlefield` | total Might of the **opponent's** units there | continuous |
| `my_units_on_battlefield` | count of my units there | continuous |
| `opponent_units_on_battlefield` | count of opponent units there | continuous |
| `i_control_battlefield` | 1 if I control it after the line, else 0 | boolean |

### Player conditions — `target` = `me` or `opponent`
| metric | meaning | kind |
| --- | --- | --- |
| `score` | the target player's victory points | continuous |
| `cards_in_hand` | the target player's hand size | continuous |
| `ready_runes` | the target player's ready (unexhausted) runes | continuous |

### This-turn outcomes — no `target` (always me, this turn)
| metric | meaning | kind |
| --- | --- | --- |
| `points_scored` | points I scored this turn | continuous |
| `enemy_units_killed` | enemy units I destroyed this turn | continuous |
| `battlefields_conquered` | battlefields I newly took & scored this turn | continuous |

### Card conditions — `target` = a card instance id
| metric | meaning | kind |
| --- | --- | --- |
| `card_played` | 1 if the named card was played in the line, else 0 | boolean |

**Excluded on purpose** (kept in the scoring overlay, not here): `*_fragility`,
`bf_control_net`, `bf_might_margin`, `ready_unit_might_diff`,
`rune_development_diff`, `cards_in_hand_net`, `hold_income`. All are
differentials/heuristics — illegible as explicit goals.

## 6. Expressibility & the engine cost

Every example condition is now expressible in the vocabulary:

| Intended condition | Clause | Status |
| --- | --- | --- |
| Conquer battlefield-b | `i_control_battlefield`, target `battlefield-b`, `== 1` | ✅ in vocabulary |
| Keep vi-1 alive | `unit_alive`, target `vi-1`, `== 1` | ✅ in vocabulary |
| Keep 2 runes ready | `ready_runes`, target `me`, `>= 2` | ✅ in vocabulary |
| vi-1 ends ≥ 4 Might | `unit_might`, target `vi-1`, `>= 4` | ✅ in vocabulary |
| Opponent hand ≤ 2 | `cards_in_hand`, target `opponent`, `<= 2` | ✅ in vocabulary |

**The cost moved from "composition" to "the engine emits a post-line state
snapshot."** Unlike the old plan (reuse the scalar scoring `features`), these
concrete metrics mostly are **not** scorer features. `TurnSearch._add_leaf()`
builds both the raw scoring `features` and a separate `search_state` snapshot via
`ScoreModel.build_search_state()`, and `_build_candidate_lines()` attaches both
to each `CandidateLine`.

- **units**: `{instance_id -> {owner, might, damage, health, battlefield, exhausted}}`
- **battlefields**: `{id, my_might, opp_might, my_units, opp_units, controller}`
- **players**: `{me|opponent -> score, cards_in_hand, ready_runes}`
- **this-turn tallies**: `points_scored, enemy_units_killed, battlefields_conquered`
- **cards played**: list of card instance ids played in the line

This is the right foundation: one snapshot resolves every implemented metric
above, and new metrics are read off the same snapshot whenever the required
quantity is already present. If a new metric needs a quantity that is not in
`search_state`, add it in `ScoreModel.build_search_state()` before adding the
Python resolver.

Adding a future metric = (1) ensure the quantity is in the snapshot (often already
there), (2) add one row to the §5 registry. The enum regenerates; the clause
"just works".

## 7. Implementation surface

**Engine (GDScript) — implemented:**
- `ScoreModel.build_search_state(leaf_snap, features, steps)` projects the
  post-line state into concrete unit, battlefield, player, turn, and card-played
  facts. A destroyed unit is absent from `units`, which is how `unit_alive`
  resolves to false.
- `TurnSearch._add_leaf()` stores `features`, `resolved_state`, `search_state`,
  `complete`, and `terminal_reason` on each leaf.
- `TurnSearch._build_candidate_lines()` serializes `search_state`,
  `expected_pre_hashes`, `complete`, and `terminal_reason` into each
  `CandidateLine`.

**Python — implemented:**
- A `SEARCH_METRICS` registry (the §5 table): metric → `{subject, kind (bool/
  continuous), resolver}`. This is the search vocabulary, distinct from
  `STATE_TARGET_METRICS` (which stays for the scoring overlay).
- `PredicateClause` + `SearchForRequest`/`SearchForResponse` in `schemas.py`;
  validate `target` against the metric's declared subject.
- `skills.search_for(...)` — `resolve(snapshot, metric, target)` per clause →
  `graded_value` (continuous) or exact (boolean) → combine → per-clause response.
- Tool schema in `agent.TOOLS` (metric enum generated from `SEARCH_METRICS`) +
  dispatch in `_dispatch_tool`.
- Tests: `tests/test_search_for.py` — multi-clause AND/weighted, empty result +
  `note`, each subject type (unit/battlefield/player/card), boolean vs graded,
  wrong-subject target rejected, off-vocab metric → no-op.



## 8. Open questions

- `combine` **default** — is weakest-link `min` right, or should the default be
`weighted` so a strong line with one weak clause still surfaces? (Lean `min`
for honesty; the `note` surfaces near-misses regardless.)
- **Snapshot growth** — the current snapshot is intentionally compact. Add fields
only when a new metric needs them; keep payload size in mind because the whole
candidate corpus crosses the Godot/Python boundary.
- **Does** `search_for` **also need a "sort by" knob** (satisfaction vs. engine
score) or is "satisfaction desc, then score desc" always right? (Start fixed.)
- **Future player metrics** — `playable_cards` was proposed but is not currently
in `SEARCH_METRICS` or `ScoreModel.build_search_state()`. Add engine support
before documenting it as a valid predicate.

