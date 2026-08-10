# Phase 2.5 — Engine-Truth Simulation (Design)

> Companion to `Memory_Roadmap.md` (Phase 2.5 entry) and
> `Phase2_Decision_Infrastructure.md`. This doc is written immediately before
> Phase 2.5 starts and supersedes the roadmap sketch where they differ. Two
> investigation findings reshaped the design and are flagged inline:
> **(F1)** Godot is currently an HTTP *client only*, not a server, so the
> roadmap's "Actor → POST /simulate to Godot" cannot be implemented as written;
> **(F2)** the headless test harness (`TcgTestHarness`) already implements the
> two hardest pieces — a headless `GameController` and an auto-pass-to-quiescence
> driver (`_resolve_chain()`).

> **Implementation status (shipped).** The initial implementation ships the
> **option-C pre-simulation** path (§5): `GameState.clone()` + `MoveSimulator.gd`
> run each legal move — and auto-detected combat lines (a contested move backed
> by an affordable Action/Reaction) — on a clone, and `BriefStateSerializer`
> inlines the `SimResult` / `LineResult` into the brief state keyed by command
> string. `skills.simulate_move` / `skills.simulate_line` look these up and
> return structured facts (the heuristic prose is deleted). The **protocol-B
> continuation** (on-demand simulation of arbitrary agent-composed lines mid tool
> loop) is **deferred** — `simulate_line` falls back to the first move's verified
> sim and an explicit "hedge the rest" note when a requested line wasn't
> pre-computed. Validator enforcement of `observed:` claims (§8.3) also remains
> follow-up work. Covered by `Scripts/Tests/Tcg/suites/RuleSimulationTests.gd`
> (clone fidelity, no-mutation, conquer, illegal-move, pre-sim inlining) and
> `ai_agent/tests/test_simulation.py`.

---

## 1. Goal — turn assumptions into evidence

Today `skills.simulate_move()` (`skills.py:198`) is a text heuristic. It returns
prose like *"you will gain control if unopposed"* or *"no simulation available;
general effect expected."* The model treats that prose as fact, which is the
direct source of bad claims such as *"this move conquers the battlefield."*

Phase 2.5's single job: **stop the agent from predicting rules outcomes it could
observe.** Outcome computation moves to the only authority that actually knows
the rules — the Godot engine — and the agent's reasoning is forced to label
every outcome claim as either:

- `observed:` — came from a simulation or is given in `brief_state` /
  `legal_moves`, or
- `expecting:` — a genuine hidden-information judgement the engine *cannot*
  resolve.

The hard design question this doc answers is **where that line sits**: what the
agent may assume vs. what it must simulate vs. what is fundamentally
unknowable. Sections 2–4 define that boundary; Sections 5–8 make it real.

---

## 2. The assumption taxonomy — what to assume, what to simulate

Every outcome claim the agent might make falls into one of four classes. The
class determines whether the agent reads it, simulates it, or hedges it. This is
the conceptual core of Phase 2.5.

| Class | Definition | Examples (Riftbound) | Agent rule |
|---|---|---|---|
| **A. Given** | Already present in `brief_state` or labeled in a `legal_moves` entry. Reading it is observation, not assumption. | Card cost/might/keywords; current battlefield controller; current scores; whose turn/priority; which moves are legal | **Assume freely.** Never spend a sim on a fact already in context. Cite as `observed:` (source = state). |
| **B. Mechanical** | The deterministic rules-engine consequence of applying a move when **no hidden opponent choice** intervenes: chain/trigger resolution, combat damage math, conquer/score deltas, units killed, costs paid, zone transitions. | "Does moving Vi into BF-a + resolving the showdown conquer it?"; "Does this spell kill their 3-might unit after my +1?"; "What's my score after this?" | **Must simulate.** This is computable but currently *guessed*. Return as fact (`observed:` from sim). |
| **C. Hidden** | Gated on the opponent's hidden cards or future free choices. The engine cannot know these without guessing. | Whether opponent holds a Reaction; which target they pick; what they draw; whether they'll contest | **Cannot be observed.** The simulator does **not** resolve these as fact; it *flags* the response window. Agent hedges as `expecting:` and may quantify using `get_opponent_history`. |
| **D. Stochastic** | An engine-known *distribution* with a random realized value (own-deck draws are known to the engine; opponent-deck and any RNG are not). | "What do I draw off a Winning Point replacement?"; dice/coin effects | Simulate the **deterministic** part; flag the random part. Default to the engine's actual next value only when it is fully determined by current state (e.g. known top of own deck). |

**The one-line rule the agent is taught:**

> If the outcome is *given* (A), read it. If it is *mechanical* (B), simulate it
> before asserting it. If it depends on the *opponent's hidden choice* (C) or on
> *randomness* (D), you may not state it as fact — name the assumption and hedge.

### Why this boundary and not "simulate everything"

Class C is the reason a full forward-search engine (MCTS/minimax over the real
game tree) is *not* the right tool here. Resolving C requires **determinization**
— guessing a concrete value for the opponent's hidden cards and searching that
"perfect-information" world (Perfect Information Monte Carlo / Information-Set
MCTS; see Section 9). Doing that well needs many sampled worlds and an
evaluation function, which is expensive and, more importantly, **invents
information the agent should reason about probabilistically instead.** Phase 2.5
deliberately simulates only the *deterministic closure* of a line (A+B, with the
default that the opponent passes) and hands C/D back to the LLM as explicit,
labeled uncertainty. The engine supplies facts; the LLM supplies judgement.

---

## 3. Single-move simulation — engine truth to quiescence

### 3.1 What "the result of a move" means with a chain

A move in a game with priority/chains has no single "next state." Returning the
immediate post-move state (a spell sitting on the chain awaiting passes) is
accurate but useless. The simulator resolves to a **stable point** (a *quiescent*
state, borrowing the chess term — see Section 9), not to the next instant:

| Stopping rule | Used when | Returns |
|---|---|---|
| **Resolve-if-unanswered** (auto-pass both seats) | every spell / ability | the concrete resolved board — the deterministic default line |
| **Next-AI-decision** | the move loops focus/priority back to the AI | state at the AI's next genuine choice |
| **Post-combat quiescence** | the move triggers a Showdown | board after simultaneous damage + heal, with `units_killed` listed |

**(F2)** The auto-pass driver already exists. `TcgTestHarness._resolve_chain()`
loops `submit_command(pi, "pass")` for whichever seat holds priority until the
chain empties or a prompt/decision point appears, with a safety bound. The
simulator reuses this exact routine; it is not new code to invent.

### 3.2 Branches: facts for the default line, flags for hidden choices

The simulator returns the deterministic **all-pass** resolution (class A+B as
fact) **plus** a flag recording that a response window opened and what class of
response is legal — without ever guessing the opponent's hidden card (class C).
The `resolved_if_unanswered` payload is ordered **headline-first** (§3.4):
win-condition fields, then board deltas, then costs, then tempo. Empty
collections are **omitted entirely** — the *presence* of a key means "something
happened here."

```json
{
  "legal": true,
  "resolved_if_unanswered": {
    "wins_game": false,
    "conquer": true,
    "my_score_after": 1,
    "opp_score_after": 0,
    "battlefields": {
      "battlefield-a": { "controller_before": "neutral", "controller_after": "me" }
    },
    "next_decision": "your main phase"
  },
  "response_window": {
    "opponent_may_respond": true,
    "legal_response_classes": ["Reaction"],
    "opponent_unknown_cards": 4,
    "note": "contested branch not resolved — opponent holds 4 unknown cards"
  }
}
```

The Actor may assert the all-pass line as fact ("conquers A *if unanswered*") but
must hedge the contested branch. This is the taxonomy from Section 2 encoded in
the return shape: `resolved_if_unanswered` is A+B; `response_window` is the C
flag.

### 3.3 Schema design principle — a decision-relevant *delta*, not a state dump

The return payload is **not** a serialized board. The agent already holds the
pre-move state in context, so re-sending the whole board wastes tokens and forces
it to diff two blobs (an error source). Every candidate field is admitted only if
it passes three tests:

1. **Delta test** — did this move *change* it? Include only changes, expressed as
   `before → after`. Unchanged state is never re-sent.
2. **Information-value test** — could this value change the agent's choice? If the
   agent picks the same move whether the field is X or Y, the field is cut.
3. **Surface-the-verdict test** — do not make the agent *infer* impact from
   primitives. The engine computes the judgement (`conquer`, `wins_game`,
   `trade`) the agent would otherwise have to derive (and would derive wrong —
   that is the very failure Phase 2.5 exists to fix).

### 3.4 Completeness by enumerating the engine's mutation surface

The hard half of schema design is *not omitting something important*. We do not
brainstorm fields — we **enumerate every state variable a move can mutate** (from
the domain classes `GameState` / `PlayerState` / `BoardState` / `CardInstance` /
`RunePool` / `ChainItem`) and prove each one either maps to a schema field or is
deliberately excluded. The mutation surface is small and closed, which makes this
a genuine completeness proof rather than a guess.

| Engine-mutable state (domain field) | Schema field | Keep? rationale |
|---|---|---|
| `PlayerState.score` (both) | `my_score_after`, `opp_score_after` | **Always** — it *is* the win condition |
| `GameState.game_over` / `winner_index` | `wins_game` | **Always** — terminal, highest signal |
| `BoardState` battlefield controller | `battlefields[id].controller_before/after` + `conquer` | **Always** — primary score engine |
| `CardInstance.location` / `battlefield_index` (zone moves, death→trash) | `units_killed`, `units_moved`, `my_units_on_battlefields`, `my_units_in_base` | **Always** — board presence |
| `CardInstance.damage` / lethal check | `units_damaged` (+ folds into `units_killed`); `trade` verdict | **Always** for combat lines |
| `CardInstance.temp_might_bonus` / `buff_counters` / `temp_keywords` | `units_buffed` | **Conditional** — only if combat/score-relevant |
| `CardInstance.is_exhausted` | `exhausted` | **Conditional** — only when it gates a follow-up move |
| `CardInstance.is_stunned` | `units_stunned` | **Conditional** — only if it changes a trade/attack |
| `PlayerState.hand` / `deck` (draw, discard, mill) | `cards_drawn` (id if own deck/known, else count), `cards_discarded` | **Always** — tempo/resource |
| `rune_pool` / energy / `channeled_runes.is_exhausted` | `energy_spent` (aggregate) | **Aggregate** — pool energy decrease, never per-rune |
| `channeled_runes` size (recycle → rune deck) | `runes_recycled` (aggregate) | **Aggregate** — net channeled loss for Power; omit if 0 |
| `chain` contents after the move | (not a resolved fact) → `response_window` | **Flag**, not state (class C) |
| `priority` / `focus` / `turn_player` next | `next_decision` | **Always** — "do I act again?" / tempo |
| `played_this_turn`, `cards_played_this_turn`, `battlefields_scored_this_turn`, `id_registry`, `_id_counters`, `player_name`, `hidden_turn_number` | — | **Excluded** — provably not decision-relevant to a move's impact |

**Maintenance rule (turns the proof into a process):** when a new mutable field
is added to any domain class, a checklist entry forces a "schema field or
documented exclusion?" decision, so the completeness proof cannot silently rot.

### 3.5 Validating the schema is neither under- nor over-built

Two empirical checks, run on recorded games, keep the schema evidence-driven:

- **Under-inclusion:** for every fact the agent's `reasoning` cites, assert it
  traces to a schema field. A cited fact with no backing field is a gap to add.
- **Over-inclusion:** measure how often each field is referenced. A field cited in
  ~0% of decisions across many games is dead weight — cut it, or demote it to a
  detail tier behind an explicit follow-up tool.

---

## 4. Multi-step (line) simulation — the combat+spell case

The roadmap only sketches single-move sim. The genuinely useful questions are
multi-step: *"if I move Vi into battlefield-a (triggering a Showdown) and then
play Decisive Strike during that combat, do I win the showdown and conquer?"*
That is two of the agent's own moves separated by an engine-driven combat
sequence. Phase 2.5 adds **line simulation**.

### 4.1 Interface

```
simulate_line(moves: [Move, ...], opponent_policy="auto_pass") -> LineResult
```

- The clone applies the agent's moves **in order**.
- Between the agent's moves the engine advances naturally (chain resolution,
  combat, triggers) using the reusable driver from §3.1.
- At each point where the **opponent** would get a choice, the simulator applies
  the `opponent_policy`. The only policy in Phase 2.5 is **`auto_pass`**: assume
  the opponent does not respond — the deterministic "if-unanswered" line. Every
  auto-passed opponent window is recorded as a branch point so the agent knows
  exactly where the line depends on the opponent doing nothing.
- At each point where the **agent** would get a choice that is *not* the next
  scripted move, the simulator stops and returns (the line under-specified the
  agent's own play — surface it rather than guess).
- Stop at quiescence after the last scripted move, or at a **ply budget**
  (default ~12 engine steps) to bound cost.

### 4.2 Return shape (`LineResult`)

`resolved_if_unanswered` is the **same delta schema** as §3 (headline-first,
omit-empty, derived verdicts), so the agent reads single-move and line results in
one shared shape. A line that resolves combat carries the `trade` verdict — the
engine-computed exchange the agent must otherwise (mis)derive.

```json
{
  "legal": true,
  "applied_moves": ["move_unit vi -> battlefield-a", "play decisive-strike"],
  "stopped_reason": "quiescence",
  "resolved_if_unanswered": {
    "wins_game": false,
    "conquer": true,
    "my_score_after": 1,
    "opp_score_after": 0,
    "battlefields": {
      "battlefield-a": { "controller_before": "neutral", "controller_after": "me" }
    },
    "controllers_after": {
      "battlefield-a": "me",
      "battlefield-b": "neutral"
    },
    "trade": "I keep vi-destructive (3 might); they lose stalwart-poro-2 (2 might)",
    "units_killed": ["enemy-stalwart-poro-2"],
    "my_units_on_battlefields": ["vi-destructive"],
    "next_decision": "your main phase"
  },
  "opponent_windows": [
    { "after_move": "move_unit vi -> battlefield-a",
      "legal_response_classes": ["Reaction"],
      "opponent_unknown_cards": 3,
      "note": "auto-passed; showdown could be contested here" }
  ],
  "first_illegal_move": null
}
```

- `applied_moves` / `first_illegal_move` tell the agent whether the whole line is
  even playable (e.g. the spell was illegal at that point because the showdown
  had already closed). This alone kills a class of fantasy plans.
- `opponent_windows` is the list of class-C branch points the agent must reason
  about. The agent can then call `get_opponent_history` to weight how likely the
  opponent is to actually hold a Reaction.

### 4.3 Why a fixed `auto_pass` policy (and not opponent search)

Searching the opponent's best response at each window is the determinization /
ISMCTS problem again (Section 9): it requires sampling the opponent's hidden
hand and an evaluator, multiplying cost and inventing information. Phase 2.5
computes the **optimistic deterministic closure** (opponent passes) and labels
the branch points. The agent — which already reasons in natural language about
"will they have an answer?" — owns the contested branch. Richer opponent
policies (`worst_case`, sampled determinizations) are explicitly future work
(Section 12).

---

## 5. Architecture — how the agent actually reaches the engine

**(F1) The roadmap's "Actor → POST /simulate" is not implementable as written.**
The agent is the FastAPI **server**; Godot's `AIPlayer.gd` is an HTTP **client**
that POSTs to `/decision` and waits. Godot has no HTTP server, and GDScript has
no turnkey one (it would mean hand-rolling `TCPServer` + HTTP parsing). The
engine that must run the sim lives on the side that cannot currently receive a
request. Three viable protocols:

| Option | Mechanism | Pros | Cons |
|---|---|---|---|
| **A. Godot HTTP server** | Embed a `TCPServer` in Godot exposing `/simulate`. Matches the roadmap diagram literally. | Clean request/response; agent stays in control | New HTTP server in GDScript; concurrency with the game loop; most code |
| **B. Continuation protocol** *(recommended)* | `/decision` may return `{"need_simulation": LineRequest}` instead of a final move. Godot runs the sim locally on a clone and POSTs the result to a new agent endpoint `/sim_result`; the agent resumes the same decision. | No server in Godot; reuses the existing pull channel; Godot already *has* the engine in-process so the clone is local and cheap | Agent decision loop becomes multi-round (state machine in `agent.py`); a few more round-trips per decision |
| **C. Pre-simulated single moves** | When Godot sends `/decision`, it also simulates each top-N legal move once and inlines `SimResult`s into `brief_state.legal_moves_simulated`. | Zero new endpoints; zero round-trips; covers most "what does this do?" questions | Wastes sims on moves the agent won't pick; **cannot** do agent-directed multi-step lines (§4) |

**Recommendation: B as the primary path, with C as a cheap accelerator.**
Godot pre-simulates each *single* legal move (C) so the common single-ply
question needs no round-trip, **and** supports on-demand `simulate_line` via the
continuation protocol (B) for the multi-step lines the agent composes itself.
Option A is rejected: embedding an HTTP server in the game process is the most
code and the most risk for no capability that B doesn't already provide, since
the engine and the sim run in the same Godot process either way.

> Net: the simulator *runs entirely inside Godot* in all options — the only
> question is how the agent asks for one. B keeps Godot a client and reuses the
> existing transport.

---

## 6. Cloning the GameState

The simulator must apply moves to a **copy** and discard it (no real mutation).
Today there is no clone path: `GameState`, `PlayerState`, `BoardState`,
`CardInstance`, `RunePool`, `ChainItem` are all `RefCounted` (`class_name X` with
no `extends`), and `RefCounted` has no deep `duplicate()`. `FixtureLoader` builds
a `GameState` *from* a dict but there is no reverse (`GameState → dict`).

Options, in order of recommendation:

1. **Explicit `clone()` per domain class** *(recommended)*. Deterministic, fast,
   testable; each class deep-copies its own fields and recurses. Cost: every new
   field must be added to `clone()` — mitigated by the fidelity test below.
2. **`to_dict()` / `from_dict()` snapshot+restore.** Reuses the existing
   `from_dict` direction and doubles as a serializer for tests/telemetry, but a
   missed field silently corrupts the clone and round-trips are slower.
3. **Convert domain classes to `Resource` + `duplicate(true)`.** Built-in deep
   copy, but invasive, and `Resource.duplicate` does not deep-copy nested
   non-`Resource` members or shares sub-resources — subtle aliasing bugs.

**Clone-fidelity test (required, regardless of option):** clone a live `gs`,
structurally hash both, assert equal; apply a move to the clone; assert the live
`gs` hash is **unchanged**. This is exactly the roadmap's "hash the live state
before/after" check, promoted to a unit test in the Tcg suite. Aliasing bugs
(clone shares a sub-object with the original) are the top risk here and this test
catches them.

---

## 7. Reusing the headless harness (the cheap path to a driver)

**(F2)** `TcgTestHarness` already runs a `GameController` headlessly:
`skip_auto_start = true`, `_ai_player_index = -1`, logs cleared, and `cmd()` +
`_resolve_chain()` drive `submit_command` through chain resolution with
auto-pass. The simulator is, mechanically, *a headless harness pointed at a
cloned `gs` with logging and `board_updated` suppressed.* Concretely:

```
SimController = headless GameController (skip_auto_start, ai_index=-1, signals muted)
SimController.gs = live_gs.clone()
for move in moves:
    cmd = move.to_command()
    SimController.submit_command(SIM_SEAT, cmd)
    if SimController.last_command_error: return LineResult(first_illegal_move=move)
    auto_pass_to_quiescence(SimController)   # == harness _resolve_chain + drain
serialize_delta(live_gs, SimController.gs) -> resolved_if_unanswered
collect opponent windows hit during the drive -> opponent_windows
discard SimController
```

This means most of Phase 2.5's Godot work is **wiring existing pieces** (clone +
harness driver + a delta serializer), not new rules code. The delta serializer
reuses `BriefStateSerializer`'s vocabulary so the agent sees sim output in the
same shape as live state.

---

## 8. How the agent uses it (accessibility & accuracy)

### 8.1 Tool surface

`skills.simulate_move()` is rewritten to return **structured facts, not prose**,
and a second tool is added:

- `simulate_move(move)` → `SimResult` (§3.2) — one ply to quiescence.
- `simulate_line(moves[])` → `LineResult` (§4.2) — a scripted multi-step line.

Both return JSON the model consumes as data. The heuristic string branches in
`skills.py` are deleted. Under protocol B (§5), the Python `skills` function
emits a `need_simulation` continuation and blocks the decision loop until
`/sim_result` arrives; under C the single-move answer may already be inlined in
`brief_state` and returned without a round-trip.

### 8.2 Prompt reinforcement (`system_prompt.py`)

- "Do **not** state what a move *will* result in unless that result came from a
  `simulate_move` / `simulate_line` call or is labeled in `legal_moves`.
  Otherwise simulate first or mark the outcome uncertain."
- Require reasoning to separate `observed:` (from sim/state — classes A/B) vs
  `expecting:` (hidden-information judgement — classes C/D).
- Teach the §2 one-line rule directly: given → read; mechanical → simulate;
  hidden/random → hedge.
- Steer toward **lines, not just moves**: "Before committing to a combat or
  contested play, simulate the *line* you intend (enter combat → the spell you'd
  back it with), not just the first move."

### 8.3 Validator integration (depends on Phase 2)

The Phase 2 Validator gains a rule: any outcome claim in `reasoning` flagged
`observed:` must correspond to a `SimResult`/`LineResult` produced for *this*
decision, or to a `brief_state`/`legal_moves` field; otherwise it is downgraded
or the decision is bounced through the existing one-shot retry with the reason
"unverified outcome claim — simulate or hedge." Claims under `expecting:` are
exempt (they are honest uncertainty). This is the mechanism that actually
converts "assumption" into "evidence" rather than relying on the model's
goodwill.

### 8.4 Keeping it accessible (not over-used)

Simulation has a cost (round-trip under B, tokens to read the result). The Router
(Phase 2) already short-circuits forced moves, so those never simulate. Guidance:
simulate when the outcome is **mechanical and decision-relevant** (combat trades,
conquer/score lines, whether a spell is even legal mid-combat) — not for moves
whose effect is fully given in `legal_moves`. Pre-sim (option C) absorbs the
cheap single-ply questions so the model spends explicit `simulate_line` calls
only on genuine multi-step lines.

---

## 9. How other systems do this (research grounding)

- **Forward model / make–unmake (chess, Stockfish).** Engines apply a move to a
  copy (or apply then undo) and read the resulting position from the rules, never
  "predicting" it. Phase 2.5's clone-apply-discard is the card-game analogue;
  option 6.2's snapshot/restore is literally make/unmake.
- **Quiescence search & the horizon effect (chess).** Searching to a fixed depth
  mis-evaluates *volatile* positions (a capture sequence cut off mid-way looks
  winning). Engines extend search at unstable nodes until the position is
  **quiet**. Phase 2.5's "resolve to quiescence, not to the next instant" (§3.1)
  is the same idea: a spell sitting on the chain is a volatile node; we resolve
  the forced exchange before serializing.
  ([Quiescence search](https://en.wikipedia.org/wiki/Quiescence_search))
- **MCTS / forward search (AlphaGo/AlphaZero, Total War AI).** General game AI
  rolls the state forward through a model and backs up outcomes. Phase 2.5
  deliberately stops at *one deterministic rollout per asked line* rather than a
  full tree — the LLM, not a search, supplies strategy. This is closer to
  Abramson's "evaluate by simulating to a stable point" than to UCT.
  ([Monte Carlo tree search](https://en.wikipedia.org/wiki/Monte_Carlo_tree_search))
- **Imperfect information: determinization, PIMC, ISMCTS.** Bridge/Skat/Hearthstone
  AIs handle hidden cards by sampling concrete "determinized" worlds and searching
  each, then averaging. The key lesson Phase 2.5 borrows is the *boundary*: you
  cannot resolve a hidden choice without inventing it. So we **flag** the
  opponent window (class C) instead of determinizing it, and let the LLM reason
  probabilistically with `get_opponent_history`. Determinized opponent policies
  are named as future work, not Phase 2.5 scope.
- **Card-game simulators (MTG Forge `GameSimulator`, Hearthstone SabberStone).**
  These clone the full game state and play candidate lines headlessly to score
  them. Phase 2.5's §7 "headless `GameController` on a cloned `gs`" is the same
  pattern — and we get it nearly for free because the **test harness already is
  that headless simulator.**
- **CICERO (Diplomacy), already cited in Phase 2.** Forms an intent, then keeps
  actions consistent with it. Phase 2.5 complements this: the Planner sets
  intent; simulation verifies the *tactics* serving that intent are mechanically
  real before they ship.

---

## 10. Schemas (`schemas.py`)

`ResolvedState` is the shared delta schema (§3.3–3.4). **Field order is
normative** — headline (win condition) → board deltas → costs → tempo — and all
collection/optional fields are **omit-empty**: absent means "no change of this
kind," so key *presence* is itself signal. Every field traces to a row in the
§3.4 mutation-surface table.

```text
Move            (exists) { action: str, parameters: dict }

SimResult       { legal: bool,
                  resolved_if_unanswered: ResolvedState,
                  response_window: ResponseWindow | null }

LineResult      { legal: bool, applied_moves: [str], stopped_reason: str,
                  resolved_if_unanswered: ResolvedState,
                  opponent_windows: [ResponseWindow],
                  first_illegal_move: str | null }

ResolvedState   {
  # ── headline: win condition (always present) ──
  wins_game: bool,
  conquer: bool,
  my_score_after: int,
  opp_score_after: int,
  # ── board deltas (omit-empty) ──
  battlefields: { id: { controller_before: str, controller_after: str } },
  controllers_after: { id: "me"|"opponent"|"neutral" },  # absolute end control (always)
  trade: str | null,              # engine-computed combat verdict, when a trade occurred
  units_killed: [str],            # omit if empty
  units_damaged: [ { id: str, damage: int } ],   # omit if empty
  my_units_on_battlefields: [str], # my units on BFs at leaf (end presence); omit if empty
  my_units_in_base: [str],        # my units newly played to base this line; omit if empty
  units_moved: [ { id: str, to: str } ],         # omit if empty
  units_buffed: [ { id: str, might_after: int } ],  # omit if empty
  units_stunned: [str],           # omit if empty
  # ── resources / tempo ──
  cards_drawn: [str] | int,       # card ids if own/known deck, else count; omit if 0
  cards_discarded: [str],         # omit if empty
  energy_spent: int,              # aggregate pool energy decrease; omit if 0
  runes_recycled: int,            # net channeled runes recycled for Power; omit if 0
  exhausted: [str],               # only units whose exhaust gates a follow-up; omit-empty
  next_decision: str              # who acts next / phase — tempo
}

ResponseWindow  { after_move: str, opponent_may_respond: bool,
                  legal_response_classes: [str], opponent_unknown_cards: int,
                  note: str }
```

**Excluded by design** (provably not decision-relevant per §3.4): per-rune
exhaust detail, `played_this_turn`, `cards_played_this_turn`,
`battlefields_scored_this_turn`, internal id registries/counters, player names,
`hidden_turn_number`. New mutable domain fields must be triaged into a field or
this list by the §3.4 maintenance rule.

Serialized identically on the Godot side (delta serializer reuses
`BriefStateSerializer` vocabulary) and parsed with the same strict discipline as
`Decision`.

---

## 11. Work items

**Godot (engine side)**
1. `GameState.clone()` (+ `clone()` on `PlayerState`, `BoardState`,
   `CardInstance`, `RunePool`, `ChainItem`). Add the clone-fidelity Tcg test
   (hash equal; live unchanged after mutating clone).
2. `MoveSimulator.gd`: builds a headless `GameController` on a cloned `gs` with
   signals/logging muted, applies a move/line via `submit_command`, drives
   auto-pass-to-quiescence (reuse the `_resolve_chain` logic), records opponent
   windows, serializes the **delta** per the §3.4 mutation-surface table (not a
   full board dump; headline-first, omit-empty). Reuse the existing legality path
   (read `last_command_error`).
3. Transport: implement protocol B — `AIPlayer.gd` handles a `need_simulation`
   response, runs `MoveSimulator`, POSTs `/sim_result`; add option C pre-sim of
   single legal moves into `BriefStateSerializer` output.

**Python (agent side)**
4. `schemas.py`: `SimResult`, `LineResult`, `ResolvedState`, `ResponseWindow` per
   §10 — normative headline-first field order, omit-empty serialization, every
   field traceable to a §3.4 mutation-surface row.
5. Rewrite `skills.simulate_move()` to return structured facts; add
   `skills.simulate_line()`; delete the heuristic string branches. Wire the
   continuation handshake into the `agent.decide()` tool loop.
6. `agent.py` tool schema: update `simulate_move` description (facts, not prose),
   register `simulate_line`.
7. `system_prompt.py`: the §8.2 edits (observed/expecting split, the §2 rule,
   "simulate lines not moves").
8. Validator rule (§8.3): `observed:` claims must trace to a sim/state field.

**Flagging:** gate behind the existing `RIFTBOUND_PIPELINE=staged` plus a
`RIFTBOUND_SIM=on|off` switch so engine-truth sim can be toggled independently
while it stabilizes.

---

## 12. Out of scope (future work)

- Opponent-response search / determinization (sampled `worst_case` policies,
  ISMCTS over the opponent's possible hands). Phase 2.5 only does the
  `auto_pass` deterministic closure and flags branch points.
- Multi-turn lookahead or full game-tree search. One line per call, to
  quiescence, bounded by a ply budget.
- Using sim outcomes to *train* anything (Phases 3–5 territory).
- Stochastic-effect distributions beyond the engine's already-determined next
  value.

---

## 13. Verification

- On the recorded "conquer" situations in `agent_tools.log`, confirm the agent's
  `reasoning` cites a `SimResult`/`LineResult` rather than asserting an
  unverified conquer; the Validator bounces unverified `observed:` claims.
- **No real mutation:** structural hash of live `gs` is identical before/after
  any sim (asserted in the clone-fidelity test and in an integration test).
- **Combat correctness:** a combat-trigger line returns a deterministic trade
  (`units_killed` / `my_units_on_battlefields`) plus an opponent Action-window flag;
  cross-check against an equivalent `RuleCombatTests` fixture.
- **Line legality:** an illegal multi-step line (e.g. spell played after the
  showdown closed) returns `first_illegal_move` set, not a fantasy resolution.
- **Schema completeness (§3.5):** replaying recorded games, every fact the
  agent's `reasoning` cites traces to a `ResolvedState` field — a cited fact with
  no backing field is a logged gap.
- **Schema over-inclusion (§3.5):** per-field reference counts across recorded
  games surface any field cited in ~0% of decisions as a candidate to cut/demote.
- **Cost:** single-ply questions resolve via pre-sim (option C) with zero extra
  round-trips; only composed lines trigger the protocol-B handshake.

---

## 14. Files changed / created

| File | Change | Summary |
|---|---|---|
| `Scripts/Domain/GameState.gd` (+ peer domain classes) | Modified | `clone()` deep-copy methods |
| `Scripts/Game/MoveSimulator.gd` | Created | Headless clone-apply-quiescence simulator + delta serializer |
| `Scripts/AI/AIPlayer.gd` | Modified | Protocol-B continuation handling; trigger pre-sim |
| `Scripts/AI/BriefStateSerializer.gd` | Modified | Inline single-move pre-sim (option C); shared delta vocabulary |
| `Scripts/Tests/Tcg/suites/...` | Created/Modified | Clone-fidelity + simulator correctness tests |
| `ai_agent/skills.py` | Modified | Structured `simulate_move`; new `simulate_line`; delete heuristic strings |
| `ai_agent/schemas.py` | Modified | `SimResult`, `LineResult`, `ResolvedState`, `ResponseWindow` |
| `ai_agent/agent.py` | Modified | Tool schema + continuation handshake in the decide loop |
| `ai_agent/system_prompt.py` | Modified | observed/expecting split; assumption rule; line guidance |
| `ai_agent/main.py` | Modified | `/sim_result` endpoint; `RIFTBOUND_SIM` flag |

No new rules logic is required on the Godot side — the simulator composes the
existing command path, chain driver, and serializer.
