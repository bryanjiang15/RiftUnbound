# Deliberative Reasoning Toolkit — Design

Status: **Phase 0–3 implemented** (Phase 4 self-play gate not yet). This doc specifies how to turn the
Riftbound agent from a *search-biasing* system into a *search-driving* one — an
LLM that investigates the game tree with live tools (conditional line search,
on-demand simulation, opponent modeling, multi-turn rollout) inside a ReAct
reasoning loop.

Companion docs:
- `Goal_Oriented_Strategist.md` — the current strategist/overlay design this
  extends. Read it first; this doc reuses its guardrails and vocabulary.
- `Phase2_5_Engine_Truth_Simulation.md` — the pre-simulation handshake this
  generalizes into live simulation.
- `Scoring_Features_Reference.md` — the linear eval and feature registry the new
  tools return facts against.

---

## 1. Motivation — why the agent feels static

The agent today is a three-stage LLM + beam-search hybrid, but **the LLM never
drives the search — it only biases and selects it.** From
`Goal_Oriented_Strategist.md`'s core principle:

> LLM picks WHAT to want; the compiler decides HOW MUCH; the search decides HOW.

That division is elegant, but it makes every LLM tool a **passive lookup**, not
an **active investigation**. Three hard walls follow:

| Wall | Where it lives | Effect |
|---|---|---|
| **No agent-driven simulation** | `skills.simulate_move` / `simulate_line` only *look up* a pre-computed `SimResult` (`skills.py:233`, `:264`). If Godot didn't pre-sim that exact command, the tool returns an error. | The LLM cannot ask "what if I do X?" for anything the engine didn't guess in advance. |
| **No opponent modeling** | `MoveSimulator.advance_to_quiescence` forces the opponent to `pass` at every response window (`MoveSimulator.gd:180-181`). Every line is `resolved_if_unanswered`. | The LLM cannot see what the opponent does back. Contested lines are labeled but never resolved. |
| **No horizon past this turn** | `TurnSearch` stops each line at `end turn` (`TurnSearch.gd:183`). | The LLM cannot reason about "where am I in two turns?" |

So when the strategist "reasons," it reads a fixed menu (`search_turn` →
pre-computed scout lines; `evaluate_position` → a static heuristic) and picks
weights. It cannot branch its own inquiry. That is why it feels static: it is
doing `read → weight → select` **once**, where a reasoning agent does
`propose → simulate → observe → refine` **many times**.

## 2. What reasoning agents do that this one doesn't

The research consensus (ReAct 2210.03629; Tree-of-Thoughts 2305.10601; RAP /
Reasoning-via-Planning 2305.14992; LATS 2310.04406; AlphaZero-style MCTS+value;
Voyager 2305.16291) converges on patterns we are missing:

1. **The LLM as a search *controller*, not a search *bias*.** The model proposes
   candidate actions, a simulator evaluates them, and the model *reads the
   results and decides where to expand next.* Simulation is an **on-demand tool
   called repeatedly**, not a one-shot pre-compute.
2. **World-model rollouts as tools (RAP).** The LLM calls "simulate this action,
   return the resulting state," then plans against the returned state. We own the
   world model (`MoveSimulator`); we just don't expose it live.
3. **Adversarial rollouts.** Strong game agents model the opponent as an active
   minimizer (expectimax / MCTS opponent nodes / self-play). Cheap version: run
   *our own* search from the opponent's seat to get their best response, then
   continue. `resolved_if_unanswered` → `resolved_vs_best_response`.
4. **Selective deepening.** Spend budget where it matters — "this line is
   critical, search it deeper" — instead of a flat fixed-depth beam.
5. **Goal-conditioned querying.** Ask the search targeted questions ("find any
   line reaching ≥2 points", "is there a line that kills their Vi?") rather than
   reading a static top-N list.

## 3. The central architectural obstacle: control inversion

**Today the control arrow points one way: Godot → Python.** Godot's `AIPlayer`
is the master loop. It runs the scout search, POSTs `/goals`, runs the main
search, then POSTs `/decision` (`AIPlayer.gd:244-314`). Python is a reasoning
service over *pushed* state; it has no way to run the rules engine — the engine
is GDScript inside the running Godot process.

Every tool in §4 requires the opposite arrow: **Python must call back into the
engine mid-reasoning.** This is the one hard problem; the tools themselves are
thin wrappers once it is solved. Four ways to solve it:

| Option | Sketch | Verdict |
|---|---|---|
| **A. Godot serves an HTTP endpoint** | Godot runs a tiny HTTP *server* (`TCPServer` + hand-rolled HTTP, or a plugin) exposing `POST /engine/simulate`, `/engine/search`. Python tools call it during the ReAct loop. | **Recommended — Phase 0 spike CONFIRMED viable (§3.1).** Keeps the engine as the single source of truth; matches the existing HTTP seam; no rules logic duplicated. The spike showed the engine search is thread-safe, so both the server *and* the heavy sim run off the main thread — no blocking of the render loop. |
| **B. Co-routine request loop** | `/decision` returns not a move but a *tool request*; Godot services it, re-POSTs with the result; repeat until the response is a move. Inverts the loop through the existing single endpoint. | Works without a Godot server, but turns one decision into a chatty multi-round handshake and tangles the endpoint contract. Fallback if A is too costly. |
| **C. Pre-expand a bigger budget up front** | Ship a deeper, wider pre-computed tree (more scout lines, opponent responses at each window) in the `/decision` payload; the LLM navigates *that* with lookup tools. | No new plumbing, but it is "static" again — just a bigger menu. Good **interim step**, not the destination. |
| **D. Port the engine to Python** | Reimplement `MoveSimulator`/rules in Python so tools run in-process. | Rejected: duplicates the rules engine, guarantees drift, enormous surface. |

**Recommendation: build C as an interim (widen the pre-computed tree, add
opponent responses), then A as the real mechanism** (a Godot-side engine server
so tools are live). C ships value immediately and de-risks the tool schemas; A
removes the pre-compute ceiling. The rest of this doc assumes A for the tool
contracts but notes where C can back a tool with no live call.

### 3.1 Phase 0 spike result — Option A is viable (engine is thread-safe)

`Scripts/Tools/ReasonerThreadSpike.gd` (run headless) settled the load-bearing
feasibility question. Results (Godot 4.6.2):

| Test | Result |
|---|---|
| T1 — `TurnSearch` on a background `Thread` | ✓ identical output to the main-thread run (thread-safe) |
| T2 — main thread free during the off-thread search | ✓ main thread kept working (spun 65× during an ~80ms search) |
| T3 — `TCPServer` HTTP request/response, headless | ✓ served request + received reply |
| T4 — request → off-thread search → reply while loop pumps | ✓ search produced lines while the loop pumped 66× |

**Why it is thread-safe:** the sim path clones `GameState`
(`build_sim_controller` → `live_gs.clone()`) and the sim `GameController` sets
`skip_auto_start=true` / `quiet_logs` and is *never added to the scene tree*, so
the search touches no shared tree state or singletons. The tree-mutating paths in
`GameController` (`get_tree()`, `call_deferred`) are game-flow only and are not
reached during pure simulation — confirmed empirically (no crash off-thread).

**Design consequence:** the engine server should run the search on a **worker
thread** (`Thread` or `WorkerThreadPool`), so a 250–800ms sim never stalls the
render loop and there is no deadlock risk. The main loop only pumps the
`TCPServer` (accept + read + dispatch to worker + write reply) — all cheap.

**One caveat surfaced:** the spike leaked Nodes at exit (`ObjectDB instances
leaked`) — from orphaned *test-harness* controllers, not the search (`TurnSearch`
already frees its sim controllers, `TurnSearch.gd:154-156`). Lesson for the
server: **free every sim controller per request**, or a long session leaks Nodes.

## 4. The tool suite

All tools return **engine-truth facts** (same contract as `simulate_move`
today): a deterministic `resolved_*` block the LLM may assert, plus explicit
uncertainty markers (`opponent_windows`, `unknown_cards`) it must hedge. Each is
a Python skill (`skills.py`) + an OpenAI tool schema (`agent.TOOLS`) + an engine
backend (live via §3-A, or a pre-computed lookup via §3-C).

### 4.1 `simulate(moves[])` — live, not lookup
Generalizes today's `simulate_line`. Runs `MoveSimulator.simulate_line` on a
fresh clone of the live state for **any** sequence, not just pre-simmed ones.
Returns `resolved_if_unanswered` + `opponent_windows`. This is the primitive the
LLM uses to test a hypothesis it formed from reading the board.

### 4.2 `search_for(goal, constraints, budget)` — conditional line search
Runs `TurnSearch` with a **leaf predicate filter**: return only lines satisfying
`goal` (a `state_target`-style predicate from the existing goal vocabulary, e.g.
`points_scored >= 2`, `enemy_units_killed >= 1`, `bf_control_net[b] >= 1`).
Backed by the same beam search, but the LLM sets the objective per-query instead
of reading a fixed top-N. This is the "find me a line that achieves X" tool —
the single highest-leverage addition, because it lets the LLM *direct* the search
rather than bias it. Reuses `goal_compiler`'s predicate machinery wholesale.

### 4.3 `simulate_opponent(from_state?, assumptions?)` — modeled response (DEFERRED)
> **Deferred** — designed here for completeness, but **not** in the near-term
> phases (§7). Build the AI-only tools (4.1, 4.2, 4.6) and the Reasoner (§5)
> first; opponent modeling lands after they prove out.

Runs `TurnSearch` from the **opponent's** seat to model their likely response,
turning a passive window into a concrete answer. The design principle (per the
2026-07 decision): **simulate on what is known, assume what is not.**

- **Known** — the opponent's board is fully visible: their deployed units,
  Might, exhaustion, battlefield control, channeled runes. The opponent search
  operates on this real state.
- **Hidden** — their hand is not visible. Rather than pretend certainty, the LLM
  supplies explicit **assumptions** as tool arguments: "assume they hold
  `noxus-cull-the-meek` (a named spell I fear)" or "assume one generic 3-cost 4-Might
  unit." The engine injects those hypothetical cards into a clone of the opponent
  seat, then searches. Every result is labeled with the assumption set it was run
  under (`assumed_cards: [...]`), so the LLM knows it is reasoning about a
  *hypothesis*, never a fact.

This makes hidden-information reasoning honest and LLM-directed: the model names
the threat it wants to stress-test, the engine tells it the mechanical
consequence *if* that threat is real. Pairs with 4.1: `simulate(my_move)` → feed
the resolved state + an assumption into `simulate_opponent` → see the answer.

### 4.4 `rollout(my_move, horizon)` — multi-turn lookahead (DEFERRED)
> **Deferred** — depends on 4.3 (needs a modeled opponent turn to thread
> forward). Sequenced after opponent modeling.

Alternates AI-search and assumption-driven opponent-search for `horizon` turns
(default 2), threading each resolved state into the next. Returns the projected
position after the horizon (as `evaluate_position` features) plus the principal
variation. Bounded expectimax with LLM-chosen roots and assumptions. Budget-capped
hard (horizon ≤ 3, per-ply node budget) so it cannot blow the turn clock.

### 4.5 `branch(move)` — enumerate what could happen (DEFERRED)
> **Deferred** — composes 4.3, so it follows opponent modeling.

Convenience composition: `simulate(move)` + `simulate_opponent` at every response
window, returning a compact tree of `{my_move → [assumed opponent answers] →
resolved}`. Answers "show me everything that could happen if I make this move" in
one call.

### 4.6 `deepen(line_id, extra_depth)` — selective iterative deepening
Re-runs `TurnSearch` seeded at an existing candidate line with more depth/budget.
Lets the LLM say "this line is critical, look harder here" instead of accepting
the flat depth-12 beam.

## 5. The reasoning loop — the Reasoner stage (chosen: 5a)

Today: strategist runs *before* the search (to bias generation), actor runs
*after* (to select). A deliberation loop that both searches and simulates blurs
that seam.

**Decision (2026-07): build 5a — collapse strategist + actor into one Reasoner
stage — on a separate branch.** The Reasoner owns the live tools (§4) and runs a
ReAct loop, emitting either a `GoalSet` (to bias a final search) or a chosen line
directly. It is a larger rewrite than upgrading the strategist in place, but it
removes the artificial pre-search / post-search split: a single stage that
investigates, then decides, is the honest shape of "the LLM drives the search."

> The rejected alternative (5b) kept the strategist/actor split and only upgraded
> the strategist's tools. Simpler, but it leaves selection stranded downstream of
> the investigation and forces all conclusions through the overlay even when the
> Reasoner has already found the exact line it wants. 5a lets the Reasoner commit
> a line directly when it is confident, or fall back to a `GoalSet` when it wants
> the search to finish the tactics.

**Branch plan:** develop 5a on a dedicated branch off `main`. The Reasoner runs
behind a new flag (e.g. `RIFTBOUND_REASONER`) so `main`'s
strategist+actor path stays intact and the two can be A/B'd in self-play (§7
Phase 5) before either replaces the other.

Loop shape, per turn, cached like the current strategist (opponent-action
invalidated):

```
Reasoner (ReAct, N rounds, one turn):
  observe    evaluate_position / search_turn (scout lines)   [grounding, forced round 0]
  hypothesize "if I contest b with Vi and hold a trick, can I score 2 and survive?"
  investigate search_for(points_scored>=2)  →  candidate line L
              simulate(L.moves)              →  engine-truth resolution of L
              deepen(L.line_id, +4)          →  is L still best when searched harder?
              [later, once 4.3 lands] simulate_opponent(after L, assume: cull-the-meek)
  refine      revise or accept
  emit        chosen line  (commit directly)   OR   GoalSet (let the search finish it)
```

The overlay/whitelist/clamp guardrails from `Goal_Oriented_Strategist.md §5`
carry over: when the Reasoner emits a `GoalSet`, it still routes through the
compiler, so a hallucinated plan degrades to a no-op overlay. When it commits a
line directly, that line is still validated against the engine's legal moves
(the current `choose_line` / decision validation path), so it can never assert an
illegal move.

## 6. Budget & guardrails (the load-bearing constraints)

Live tools mean the LLM can spend unbounded engine time. This is the primary
risk and needs hard caps:

1. **Per-turn tool budget.** A total node/time budget for the whole ReAct loop
   (e.g. 1500 nodes / 3s across all `simulate`/`search_for`/`rollout` calls),
   decremented per call and surfaced to the LLM ("budget 40% remaining") so it
   self-triages. Exhaustion ends the loop and forces an emit.
2. **Rollout horizon cap** ≤ 3; opponent search width smaller than main search.
3. **Latency.** Each live call is a Godot round-trip (~250–800ms today). Batch
   independent tool calls in one round; run the loop async; cache aggressively
   (a `simulate` result is a pure function of state+moves — memoize by
   structural hash, reusing `ScoreModel.structural_hash`).
4. **Opponent-hand honesty.** Never present a hidden-information rollout as
   certain. Every `simulate_opponent`/`rollout`/`branch` result carries an
   explicit `hidden_info` marker and returns a response distribution.
5. **Fails safe to today's agent.** Any tool error, budget exhaustion, or engine
   unavailability degrades to the current path: empty overlay → base-profile
   search → `choose_line`. No new failure can crash a turn.
6. **Determinism for tests.** Live tools must be seedable/mockable so
   `tests/` can assert tool behavior without a running Godot (mirror the existing
   pre-sim fixtures in `test_simulation.py`).

## 7. Phasing

Near-term work is the **AI-only** tools plus the Reasoner. Opponent modeling
(4.3–4.5) is **deferred** by decision — the AI-only loop must prove out first.
All Reasoner work lands on a **separate branch** behind `RIFTBOUND_REASONER`
(§5), so `main`'s strategist+actor path is untouched and A/B-able.

| Phase | Deliverable | Ships value | Depends on |
|---|---|---|---|
| **0** | ✅ **DONE** — spike (`Scripts/Tools/ReasonerThreadSpike.gd`, §3.1) confirmed: engine is thread-safe, `TCPServer` serves headless, main loop stays free. Decision: engine server runs sims on a **worker thread**. | De-risks the whole live-tool path | — |
| **1** | ✅ **DONE** — `search_for` over pre-computed lines with per-line `search_state` (Python `SEARCH_METRICS` filter; fuller than the original “per common predicate” sketch). | Conditional search, no Godot server | — |
| **2** | ✅ **DONE** — Godot `EngineServer` (`POST /engine/simulate`, `/engine/search`); live `simulate` / `deepen` / `search_for` with Phase-1 fail-safe fallback. | Live "what if X?" | Phase 0 |
| **3** | ✅ **DONE** — Reasoner stage (§5a) on its own branch: ReAct loop over the AI-only tools (4.1, 4.2, 4.6), per-turn tool budget (§6), emits chosen line or `GoalSet`. | **The deep-planning payoff** | Phase 2 |
| **4** | SPRT self-play gate — Reasoner seat vs. current strategist+actor seat; commit only on a significant win-rate lift (`Goal_Oriented_Strategist.md §8`). | Evidence it helped | Phase 3 |
| **5+** *(deferred)* | Opponent modeling: `simulate_opponent` (4.3, assumption-driven) → `branch` (4.5) → `rollout` (4.4), each behind the same gate. | Adversarial + multi-turn reasoning | Phase 3 |

## 8. Open questions

- ~~**Godot-while-blocked (Phase 0 spike)**~~ — **RESOLVED (§3.1).** The engine
  search is thread-safe, so the server runs sims on a worker thread: no render-loop
  stall, no deadlock. The main loop only pumps the cheap `TCPServer` accept/read/
  write; heavy work is off-thread. Remaining sub-task: free every sim controller
  per request (the spike's leak lesson).
- **Emit contract** — when should the Reasoner commit a line directly vs. emit a
  `GoalSet` and let the search finish? Needs a clear rule (e.g. commit only when
  a `simulate`'d line dominates and is uncontested; else hand off a `GoalSet`).
- **Opponent assumptions UX (deferred, 4.3)** — resolved in principle: simulate
  on the known board, let the LLM name hidden-card assumptions per query, label
  every result with its assumption set. Open sub-question: seed a *default*
  assumption set from opponent history / archetype (ties into `Memory_Roadmap.md`
  LTM work) so the LLM does not have to specify from scratch each time.

## 9. Prior art

ReAct (2210.03629); Tree-of-Thoughts (2305.10601); Reasoning-via-Planning / RAP
(2305.14992, LLM-as-world-model); LATS (2310.04406, LLM + MCTS + reflection);
Voyager (2305.16291, tool/skill self-construction); AlphaZero (MCTS + learned
value, the opponent-node pattern §4.3 borrows). Shared caution — **search cost
explosion and hidden-information overconfidence** — is handled by the §6 budget
caps and honesty markers.
