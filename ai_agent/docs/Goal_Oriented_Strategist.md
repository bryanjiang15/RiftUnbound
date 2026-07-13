# Goal-Oriented LLM Strategist — Design & Implementation

Status: v0 implemented + tested: server-side re-rank, engine-side overlay
primitive, live engine handshake, and search-grounded scout flow. Goal telemetry
and the SPRT gate are scoped follow-ups.

Companion docs:
- `Score_Tuning_And_Evolution.md` §5 (cross-turn planner hook) — the seam this
  feature fills.
- `Scoring_Features_Reference.md` — the linear eval, the registry, and the
  situational-feature scaffold the specific-goal mechanism reuses.

---

## 1. Motivation

The strongest agent is the **search AI**: `TurnSearch` beam-searches one turn and
ranks lines with a static linear eval (`ScoreModel` → `FeatureRegistry` →
`ScoringProfile`, weights in `Data/AI/scoring_profile.json`). It is strong but
**does not reason and its objective is fixed for the whole game**.

This feature adds a per-turn **LLM strategist** that reads the state, proposes a
small set of **goals**, and **temporarily biases the scoring profile** the search
optimizes. The base tuned profile is never mutated — the bias is a transient,
one-turn overlay.

Division of labor (the design's core principle):
**LLM picks WHAT to want (semantics); the compiler decides HOW MUCH (magnitude);
the search decides HOW (tactics); self-play decides WHETHER it helped (the gate).**
The LLM never writes raw weights — verified weak at numeric optimization
(`Score_Tuning §4.3`, OPRO), strong at directions/semantics.

## 2. Components

| # | Component | File | Role |
|---|---|---|---|
| A | Strategist (LLM) | `ai_agent/strategist.py` | once/turn (cached, opp-action-invalidated) emits a structured `GoalSet` (≤4 goals) |
| B | Goal compiler (deterministic) | `ai_agent/goal_compiler.py` | pure `GoalSet → ProfileOverlay`, whitelist + clamp |
| C | Worker (search) | `Scripts/Game/TurnSearch.gd` | runs under `base ⊕ overlay` |
| — | Goal vocabulary | `ai_agent/system_prompt.py:goal_vocabulary_block()` | the menu of features/metrics a goal may reference, generated from `feature_registry.json` |

`GoalSet` / `Goal` schemas live in `ai_agent/schemas.py`.

## 3. Two bias mechanisms

### 3.1 Weight modulation (generic goals → continuous lean)
`kind="weight_bias"`: a clamped multiplier on an existing registry weight (e.g.
`battlefield_control ×2.0`). Smooth, low risk — it only re-weights terms the eval
already has. Applied BOTH engine-side (biases search generation) and in the
server re-rank.

### 3.2 Situational goal-predicate bonus (specific goals → discrete objective)
`kind="state_target"` / `kind="card_target"`: a bonus that fires when a board
predicate is met (`my_ready_runes >= 3`, `bf_control_net[battlefield-b] >= 1`,
"played card X"). Reuses the **existing empty `situational_weights` scaffold**.
Predicates are **graded, not binary** (`goal_compiler.graded_value`) so the beam
search sees a gradient toward the goal rather than a flat plateau. Currently
applied as a **selection re-rank** (the engine lacks a leaf-predicate evaluator).

## 4. Data flow

```
BriefState
  └─ optional cheap base-profile scout search (engine; top candidate lines)
       └─ POST /goals with BriefState + scout lines
            └─ Strategist LLM (once/turn) ─► GoalSet
                 └─ goal_compiler.compile_goals ─► ProfileOverlay
                      └─ overlay.weight_multipliers returned to engine

Main TurnSearch:
  ScoringProfile.apply_overlay(weight_multipliers)
    -> generic goals shape line GENERATION

POST /decision with searched candidate lines:
  choose_line adjusted_score(line) = line.score + overlay_delta(line)
    -> all goals shape SELECTION
```

The strategist is cached per turn, so the `/goals` and `/decision` calls in the
same turn reuse one GoalSet (one LLM call) — generation and selection share the
exact same overlay.

`overlay_delta` is exact for weight bias (`(m−1)·breakdown[term]`, since
`term = weight·feature`), and `weight·graded_value` for situational terms.

When the scout is enabled, the engine runs it with the base scoring profile
before `/goals` and sends only the top few lines. The Strategist's first tool is
then `search_turn`, so its goals are grounded in the engine's actual candidate
space. If the scout finds zero or one line, the engine skips `/goals`: there is
nothing for a goal overlay to bias, and `/decision` short-circuits selection to
the single line. If the scout is disabled, the strategist falls back to the
snapshot-grounded path and uses `evaluate_position` first.

## 5. Guardrails

1. **Whitelist + clamp** in the compiler: weight_bias targets must be registry
   spec ids (loaded from `feature_registry.json` so they can't drift);
   state_target metrics must be in `STATE_TARGET_METRICS`; multipliers clamp to
   `[0.5, 2.5]`; bonus weights come from a priority→magnitude table. Anything
   off-menu compiles to a **no-op**, never a crash or unbounded weight.
2. **Shaping clamp reuse**: bonuses ride inside `shaping`, which
   `ScoringProfile.gd` already clamps below `win_game − 1`, so **no goal can
   outweigh a real win/loss** (potential-based-shaping safety, Ng et al. 1999).
3. **≤4 goals** — avoids multi-objective soup.
4. **Graded predicates** — search gets a gradient, not a plateau.
5. **Transient** — overlay is rebuilt each turn; the base profile is never
   mutated.
6. **Fails safe to today's AI** — empty/invalid GoalSet ⇒ empty overlay ⇒ base
   profile selection. Off by default (`RIFTBOUND_GOALS=off`).

## 6. Context sizing (how much does the strategist need?)

**Rules: kept at the planner's level** (`goal_and_role` + `core_rules` +
`keywords_in_play`). The strategist steers toward the win condition; it does NOT
get `combat_rules_detailed` or `priority_focus_rules` — those are tactical, owned
by the search, and reachable on demand via `lookup_rule`. Adding them would dilute
the strategic frame and waste tokens.

**The one load-bearing addition is the goal-vocabulary block** — a feature
dictionary + snapshot-metric allowlist + comparators, generated from the compiler's
own whitelists so the menu can never drift from what the compiler accepts. Without
it the LLM invents metric names that compile to no-ops. Net prompt size ≈ neutral.

## 7. Configuration

| Env var | Default | Description |
|---|---|---|
| `RIFTBOUND_GOALS` | `off` | Enable the per-turn strategist + goal overlay (requires `RIFTBOUND_SEARCH=on`, ignored under `RIFTBOUND_SEARCH_ARGMAX`). |
| `RIFTBOUND_GOALS_SCOUT` | `on` | Engine-side toggle (`Scripts/AI/AIPlayer.gd`). When goals are on, run a cheap base-profile scout search before `/goals` and send its top lines for `search_turn` grounding. Falsey values (`0`, `false`, `no`, `off`) disable the scout. |
| `RIFTBOUND_LOG_INPUTS` | `0` | When combined with `RIFTBOUND_SEARCH=on`, writes `ai_agent/agent_search.log` with searched candidate lines, search stats, goal overlays, and per-line overlay deltas. |

## 8. What is implemented vs. follow-up

**Implemented + tested**
- `Goal` / `GoalSet` schemas (`schemas.py`).
- `goal_compiler.py` (compile + `overlay_delta` + `graded_value`) —
  `tests/test_goal_compiler.py` (17 cases).
- Goal-vocabulary prompt module (`system_prompt.py`).
- `strategist.py` (cached per-turn GoalSet emitter, mirrors the Planner).
- Overlay-aware line selection (`agent.choose_line` / `_argmax_line`) +
  `build_goal_overlay` orchestrator, wired in `main.py` behind `RIFTBOUND_GOALS` —
  `tests/test_choose_line_overlay.py` (4 cases).
- Engine overlay primitive: `ScoringProfile.apply_overlay` +
  `TurnSearch.new(path, overlay)` — `RuleScoreFeaturesTests.gd` (2 cases).
- **Pre-search `/goals` handshake (end-to-end):** `POST /goals` endpoint +
  `goals_enabled` in `/health` (`main.py`); engine fetches the overlay before the
  main search and builds `TurnSearch` with it (`AIPlayer.gd` `_fetch_goal_overlay`).
  Verified end-to-end: `/health` advertises the flag, `/goals` returns the
  compiled overlay, and `/decision` re-ranks under the same cached overlay,
  flipping selection to the goal-satisfying line.
- **Search-grounded scout flow:** `AIPlayer.gd` runs a small base-profile scout
  search before `/goals` when `RIFTBOUND_GOALS_SCOUT` is not falsey, sends the top
  five lines to `GoalsRequest`, and skips `/goals` when the scout finds at most
  one line. `skills.search_turn` serves those summaries to the Strategist, which
  forces `search_turn` as its first tool when scout lines are present.

**Runtime path (live):** with `RIFTBOUND_SEARCH=on RIFTBOUND_GOALS=on` and
`OPENAI_API_KEY` set, the system runs end-to-end. Generic (weight_bias) goals bias
both search generation (via the handshake) and selection; specific
(state_target / card_target) goals bias selection (re-rank). No key / strategist
error ⇒ empty overlay ⇒ today's base-profile search.

For debugging, also set `RIFTBOUND_LOG_INPUTS=1`. `agent_search.log` then shows
the candidate lines the engine sent, search stats, the compiled overlay, and the
per-line deltas that changed selection.

**Follow-up (scoped, not yet built)**
- An engine-side leaf-predicate evaluator so `state_target` / `card_target` goals
  also bias search *generation* (today they bias selection only; generic goals
  already bias generation via the handshake).
- `telemetry`: persist `goal_set` + per-goal `achieved`-at-leaf into
  `search_decisions`.
- `sprt-gate`: strategist seat vs base seat in `SelfPlaySim.gd`; commit the
  mechanism only on a significant win-rate lift.

## 9. Prior art

Hierarchical RL / manager–worker goal-conditioning (Feudal RL; FeUdal Networks);
potential-based reward shaping (Ng, Harada & Russell 1999); LLM-proposer +
simulator-judge (OPRO 2309.03409, Eureka 2310.12931, FunSearch, Voyager
2305.16291); GOAP (goal predicates as satisfaction conditions). Shared caution —
**goal misspecification / reward hacking** — is handled by the §5 guardrails and
the (follow-up) win-rate gate.
