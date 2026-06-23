# Phase 2 — Agent Decision Infrastructure

## Goal

Replace the single monolithic model call in `agent.decide()` with a small
staged pipeline — **Router → Planner → Actor → Validator** — so that each
decision spends tokens where they matter, stays consistent across the many
decisions within one turn, and never ships an unverified or illegal move to
Godot. This is the structural prerequisite for Phase 2.5 (simulation) and makes
every later memory phase more effective.

---

## What Phase 2 Aims to Fix

Grounded in the current code and one recorded game's `agent_inputs.log`.

### Problem 1: The whole rulebook is re-sent every decision

`build_system_prompt()` is rebuilt and prepended on every call
(`agent.py:440`). Measured over one recorded game, the system block averaged
**~9,200 characters per decision** (min 8,529, max 12,021) across 11
decisions — most of it identical rules text that the model has already seen.

### Problem 2: Forced/trivial decisions pay full price

The log contains decisions with exactly **one** legal move (`end turn`) that
still carry the complete strategic + rules payload and still make a full model
call. A single turn often contains 5–6 decisions (e.g. Turn 3 in the log), each
re-strategizing from scratch with no shared context.

### Problem 3: One call does four jobs

Reading state, recalling rules, forming strategy, and emitting a schema-valid
legal action are all crammed into a single `chat.completions.create()` loop.
That coupling is why reasoning quality and output-legality failures are hard to
isolate, and why contradictory lines appear across the decisions within one
turn — nothing holds a stable intent.

---

## New / Changed Components

| Component | Today | Phase 2 |
|---|---|---|
| `router.py` (new) | — | Pure-Python Stage 0: forced-move short-circuit + prompt-module + "needs plan?" routing. Zero tokens. |
| `planner.py` (new) | — | Stage 1: one LLM call per *turn* that emits a small JSON intent; cached and reused by every decision in that turn. |
| `agent.decide()` | monolithic loop | Stage 2 "Actor": orchestrates router/planner, runs the small routed prompt + typed legal actions + tool loop. |
| `validator` (in `agent.py`) | legality retry only | Stage 3: legality **and** plan-consistency gate, with one targeted retry carrying the reason. |
| `system_prompt.py` | full rules every turn | Router selects the minimal module set; detailed rules stay behind `lookup_rule` / `get_keyword`. |
| legal-move surface | free-text command strings | typed action objects handed to the Actor (text kept for back-compat/logging). |

---

## Data Flow

```
POST /decision { brief_state, game_id, rejection_context }
      │
      ▼
STAGE 0 — ROUTER (no LLM)
  • len(legal_moves)==1            → return that move immediately (no model call)
  • classify decision_type         → choose prompt module(s)
  • needs_plan?  main_phase / showdown_focus = yes
                 pending_choice / forced     = no
      │
      ▼ (if needs_plan and no cached plan for this turn)
STAGE 1 — PLANNER  (LLM call #1, cached per (game_id, turn_number))
  in : board summary + rolling memory summary + last turn's intent
  out: { intent, primary_target, threat_read, plan_for_turn }   (JSON)
      │  (cached; reused by every later decision in the same turn)
      ▼
STAGE 2 — ACTOR    (LLM call #2, every non-trivial decision)
  in : small routed prompt + plan + current decision state + TYPED legal actions
  tools: list_legal_moves, get_card_detail, lookup_rule, simulate_move (Phase 2.5)
  out: Decision JSON (action + parameters)
      │
      ▼
STAGE 3 — VALIDATOR (no LLM; optional single retry)
  • action ∈ legal_moves?                     (exists today)
  • action consistent with plan.intent?       (new)
  • confidence floor / schema sanity          (new)
  → fail: one retry with the specific reason (reuses rejection_context path)
  → pass: return Decision
      │
      ▼
to_command() → Godot validates → /outcome, /opponent_action → Memory
```

---

## Key Design Points

### Per-turn plan caching (the consistency win)

A single Riftbound turn produces many decisions (Turn 3 in the log: move_unit,
showdown_focus, main_phase, two pending_choice, end). Today each is strategized
independently, which is where contradictory lines come from. Phase 2 computes
**one plan per (game_id, turn_number)** in Stage 1 and threads it through every
Stage 2 call that turn. This mirrors CICERO's "form an intent, then keep
dialogue/actions consistent with it" pattern. The cache is invalidated when
`turn_number` advances or the opponent takes an action that materially changes
the board (detected via a **strategic-state hash**, not full `brief_state`).
Volatile fields (`legal_moves`, pending-choice prompt text, other per-decision
metadata) are excluded so we do not replan unnecessarily within the same turn.

### Typed legal actions

`legal_moves` is currently natural-language strings the model must pattern-match
against the JSON output contract (a known source of mismatch — see the
`destination` quoting / `from_hidden` edge cases already special-cased in
`agent.py`'s retry text). Phase 2 has the Actor consume **structured** action
objects (`{action, params, label}`) so "which legal action" becomes a selection
over a typed list rather than string reconstruction. The text form is retained
for `timeline_slice()` and logs.

### Validator flexibility for tactical windows

Plan-consistency is strict for broad strategic decisions (`main_phase`,
`showdown_focus`) and soft for tactical windows (`pending_choice`,
`chain_reaction`, `combat_assignment`) where immediate legal responses may
correctly deviate from the turn plan.

---

## Work Items

1. `router.py`: `route(brief_state) -> RouteDecision{forced_move?, modules[],
   needs_plan}`. Unit-test the forced-move short-circuit against recorded
   single-legal-move decisions from `agent_inputs.log`.
2. `planner.py`: `plan(brief_state, memory_summary, last_intent) -> Plan`. JSON
   schema + a strict parser (reuse the `Decision` parsing discipline). Add an
   in-process `{ (game_id, turn): Plan }` cache with **strategic-state hash**
   invalidation (exclude volatile per-decision fields).
3. Refactor `agent.decide()` into the Actor stage: consume router output, fetch
   or build the plan, assemble the **small** prompt, run the existing tool loop.
4. Promote the post-parse check into an explicit Validator with the new
   plan-consistency rule (strict for strategic decisions, soft for tactical
   windows); route failures through the existing one-shot retry.
5. Split `system_prompt.py` so the router can request just
   `{core, output_contract, <decision-module>}` instead of the full assembly.
6. Emit typed legal actions from the brief-state formatter; keep the string list.
7. **Feature flag** `RIFTBOUND_PIPELINE=staged|legacy` (default `legacy` until
   verified), matching the existing `RIFTBOUND_LOG_INPUTS` pattern, so the whole
   pipeline can be toggled off instantly.

---

## What Phase 2 Does NOT Include

- Engine-truth simulation / the `/simulate` endpoint (Phase 2.5 — depends on the
  Actor/Validator stages existing here first).
- Any cross-game storage, reflection, or retrieval (Phases 3–5).
- Claude migration or prompt caching (Phase 7) — though the stable-prefix split
  in work item 5 makes that migration cheaper later.
- Any change to the LLM model used.

---

## Verification

- Replay one recorded game through `staged` and `legacy`; diff `agent_inputs.log`
  to confirm trivial decisions make **zero** model calls and non-trivial system
  payload shrinks substantially from the ~9.2k-char baseline.
- Assert one Planner call per turn (not per decision) via a call counter.
- Confirm no regression in legal-move acceptance rate (`decisions.accepted`).

---

## Files Changed / Created

| File | Change Type | Summary |
|---|---|---|
| `ai_agent/router.py` | Created | Stage 0 routing: forced-move short-circuit, prompt-module selection, needs-plan flag |
| `ai_agent/planner.py` | Created | Stage 1 planner: per-turn JSON intent + in-process plan cache with hash-diff invalidation |
| `ai_agent/agent.py` | Modified | `decide()` becomes the Actor stage; explicit Validator with plan-consistency gate |
| `ai_agent/system_prompt.py` | Modified | Splittable assembly so the router can request a minimal module set |
| `ai_agent/schemas.py` | Modified | `Plan` schema; typed legal-action objects |
| `ai_agent/main.py` | Modified | `RIFTBOUND_PIPELINE=staged|legacy` flag wiring |

No Godot-side change is required in Phase 2 (that begins in Phase 2.5).
