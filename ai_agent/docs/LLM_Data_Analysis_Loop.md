# Post-Game Analysis & Hypothesis Loop — Design Doc

Status: **design** (analyst not built). Data/tuning foundation is largely in place
— see §0 and companion docs for what already ships.
Scope: **post-game / offline** analysis — how an LLM (or a human with the same
tools) inspects telemetry, searches counterfactual lines, forms typed hypotheses,
and routes them to deterministic validators. Not the live decision loop.

Companion docs:
- `Statistical_Analysis_Storage.md` — schema and capture (much of §2–3 shipped).
- `Score_Tuning_And_Evolution.md` — Texel/CMA-ES, delayed-value features, LLM
  roles in tuning (hypotheses + feature invention).
- `Goal_Oriented_Strategist.md` — live per-turn GoalSet → scoring overlay.
- `Deliberative_Reasoning_Toolkit.md` — live `search_for` / `simulate` / `deepen`
  and deferred multi-turn `rollout` (engine tools this loop reuses offline).

Guiding principle (unchanged):
**the LLM hypothesizes and explains; deterministic tooling decides.**

---

## 0. Current architecture (what the analyst looks at)

The live agent is no longer “LLM picks among scored lines only.” Post-game
analysis must understand the full stack:

```
TurnSearch (beam, linear ScoringProfile)
  ↑ optional GoalSet overlay (RIFTBOUND_GOALS) from Strategist
  ↑ optional live engine tools (search_for / simulate / deepen via EngineServer)
  → choose_line (LLM | argmax | single-line short-circuit)
```

| Mode | Flags | What post-game can trust |
|---|---|---|
| **Argmax self-play** | `SEARCH=on`, `SEARCH_ARGMAX=on` | Pure search + weights. Best for Texel / weight A/B. |
| **LLM selector** | `SEARCH=on`, goals off | Selection vs eval vs search error (classic triad). |
| **Goals on** | `SEARCH=on`, `GOALS=on` | Also **goal error** (bad overlay steered generation/selection). |
| **Reasoner** | `RIFTBOUND_REASONER=on` | Also **investigation / commit** error (tool misuse or direct line commit); see `reasoner_decisions`. |

Always stratify aggregates by `origin` (`self_play` / `vs_human` / `vs_heuristic`)
and `selector_source` (`argmax` / `llm` / `fallback` / `single`). Never mix
argmax weight-tuning data with goals-on quality data without saying so.

### 0.1 What already ships (do not re-plan)

| Piece | Where |
|---|---|
| Tuning tables | `search_decisions`, `candidate_lines`, `decision_snapshots`, `weight_versions`, `card_events` in `memory.py` |
| Goal / overlay telemetry | `search_decisions.goals_source` / `goal_set_json` / `overlay_json` / `chosen_overlay_delta` / `chosen_goal_achieved_json` |
| Reasoner summary | `reasoner_decisions` (+ compact `tool_trace` on `/reason` telemetry) |
| Turn pulses | `turn_snapshots` via `/turn_snapshot` + self-play JSONL |
| Outcome backfill | `/game_over` → `game_outcome`, `final_score_diff`, `went_first` |
| Self-play harness | `SelfPlaySim.gd` + offline JSONL capture / `import_selfplay_logs.py` |
| Deterministic reports | `feature_report.py`, `card_report.py`, `texel_tune.py` |
| Live goal bias | Strategist + `goal_compiler` (`Goal_Oriented_Strategist.md`) |
| Live conditional search | `skills.search_for` + `EngineServer` (`Deliberative_Reasoning_Toolkit.md` Phases 0–2) |

### 0.2 Gaps the analyst still needs

| Gap | Why it matters |
|---|---|
| `hypotheses` + `tuning_runs` | Audit trail for the loop below |
| Typed analysis API + briefing generator | §1–2 (not built) |
| Offline counterfactual line search | §3 (not built; reuses EngineServer) |

---

## 1. Why a dedicated analysis layer

Three failure modes if you “just give the LLM the database”:

1. **Context blow-up.** Thousands of `search_decisions` rows degrade numeric
   reasoning. Feed **schema + aggregates + small slices**, never raw dumps.
2. **Spurious correlations.** Many features ⇒ multiple-comparisons explosion.
   Hypotheses must be **pre-registered** and tested on **held-out** data.
3. **Ungrounded numbers.** LLMs are weak at weight *values*. Emit **directions
   and structured proposals**; Texel/CMA-ES + SPRT decide.

---

## 2. How data is presented

### 2.1 Tier A — always in context (≤ ~2–3k tokens)
Deterministic **analysis briefing**:

- **Schema card** — table names/columns/semantics for tuning tables + `games`.
- **Feature dictionary** — ~30 scoring terms with weight, sign, one-line meaning
  (from `scoring_profile.json` + `Scoring_Features_Reference.md`).
- **Dataset summary** — n games/decisions, win rate, date range, origin mix,
  `selector_source` mix, weight_version coverage, goals-on fraction (when logged).
- **Headline aggregates** (markdown tables, ~3 sig figs):
  - Feature impact (`feature_report.py`)
  - Feature→outcome effect sizes (wins vs losses)
  - Card stats (`card_report.py`, min-N gated)
  - Failure-mode sketch counts (§4) when telemetry allows

### 2.2 Tier B — on-demand typed query tools
Read-only, parameterized tools; results capped (e.g. ≤30 rows) as markdown.
**No raw SQL against the live DB.**

### 2.3 Tier C — qualitative + counterfactual drill-down
A handful of full decisions (board snapshot, candidates + breakdowns, chosen
line, outcome) **plus**, when useful, engine counterfactuals from §3.
Sample deliberately (highest-regret losses, late collapses), not at random.
Cap ~3–5 examples per request.

**Takeaway:** aggregates for *what*, a few concrete games (+ optional
counterfactual lines) for *why*.

---

## 3. Counterfactual line search (missed wins & later goals)

Highest-value **new** analysis capability. Distinct from live play: budget and
assumption honesty matter more than latency, and results are diagnostic, not
moves to ship.

Inspired by chess game review (Stockfish MultiPV / missed mate), Hearthstone
missed-lethal tools (e.g. LethalCue), and the deferred `rollout` design in
`Deliberative_Reasoning_Toolkit.md`. TCG research (TCG-Bench, PTCG-Bench)
repeatedly shows late losses and missed close-outs as the dominant failure mode.

### 3.1 Same-turn: “was there a winning / goal line *now*?”

Offline, on a stored `decision_snapshot` (or pinned engine state):

1. Restore state via `EngineServer`.
2. `search_for` with concrete predicates (`my_score >= 8`, `points_scored >= 2`,
   kill/control clauses — see `schema/search_for_tool_schema.md`).
3. Optional `deepen` / `simulate` on matches.
4. Compare to the played line → **missed win**, **missed goal**, or **not in
   beam** (search coverage gap).

This is the cheap, high-precision slice. Prefer it before multi-turn rollouts.

### 3.2 Multi-turn: “was there a better setup for a later goal?”

For swing turns in lost (or high-regret) games, run a **bounded** counterfactual:

```
restore snapshot S
propose roots: played line | top candidates | analyst-named hypotheses
for horizon H ≤ 2 (hard cap):
  AI TurnSearch from current state
  opponent reply under LABELED assumptions (known board; named/generic cards)
  score leaf: win? score proximity? goal predicate? eval features?
report: line L, horizon H, assumption set A, leaf summary
```

This is the offline counterpart of deferred live `simulate_opponent` + `rollout`.
**Every result must carry its assumption set.** Hidden hands and draws make
“winning in two turns” conditional — report *winning under A*, never as certain
blunder proof.

### 3.3 Analysis tools (engine-backed)

| Tool | Returns |
|---|---|
| `search_for_on_snapshot(game_id, turn, decision_index, constraints, …)` | Same-turn goal/win matches from a logged decision |
| `counterfactual_rollout(game_id, turn, decision_index, root, horizon, assumptions)` | Projected leaf + PV under labeled assumptions |
| `compare_to_played(…)` | Diff: played vs counterfactual (score, predicates, regret-style delta) |

Live `search_for` / `simulate` / `deepen` stay for the Reasoner; these wrap the
same engine for **logged snapshots** and batch review.

### 3.4 When this is useful vs not

| Use | Verdict |
|---|---|
| Post-game missed same-turn wins/goals | **Build first** — falsifiable, high signal |
| Post-game 1–2 turn rollouts on swing turns | **Build second** — fuels feature/goal diagnosis |
| Live unbounded multi-turn search every decision | **Avoid** — cost + hidden-info noise; keep delayed value in the leaf eval (Score_Tuning §1) |

---

## 4. Failure-mode triage (expanded)

Before proposing weight changes, classify each bad decision. Routing wrong
causes useless tuning.

| Mode | Signal | Fix elsewhere |
|---|---|---|
| **Selection error** | Better candidate in top-N; `regret > 0`; selector=`llm` | Line-selector / prompts |
| **Search error** | Counterfactual or realized-best line never in beam | Beam/depth/budget; `search_for` coverage |
| **Eval error** | Best line generated but mis-scored vs outcome | **Weight / feature tuning** |
| **Goal error** | GoalSet/overlay steered search away from a clearly better line | Strategist prompts / vocabulary; not base weights |
| **Investigation error** *(Reasoner)* | Tools available but unused/misused; missed `search_for` hit | Reasoner prompts / tool policy |
| **Commit error** *(Reasoner)* | Direct line commit illegal or dominated by search | Emit-contract / validation |
| **Horizon / setup miss** | Same-turn eval fine; counterfactual shows better later goal under mild assumptions | Delayed-value **features** or sharper goals — not deeper live search by default |

Classic triad (selection / search / eval) still applies to argmax and
selector-only games. Goals-on and future Reasoner **add** rows above; they do
not retire the triad.

---

## 5. Typed analysis tools (DB surface)

Start with a small read-only API (ReAct-callable). Prefer wrapping existing CLIs.

| Tool | Purpose |
|---|---|
| `feature_outcome_stats(…)` | Per-feature mean in wins vs losses, effect size, n |
| `feature_impact(…)` | Wraps `feature_report.py` |
| `card_stats(…)` | Wraps `card_report.py` |
| `slice_winrate(group_by, filters)` | Conditional win rate |
| `cohort_compare(weight_version_a, b)` | A/B summary |
| `sample_decisions(filter, order_by, limit≤5)` | Tier-C snapshots |
| `failure_mode_summary(filters)` | Counts from §4 when telemetry allows |
| + §3.3 engine tools | Counterfactual drill-down |

Later (optional): sandboxed Python over a **read-only dataframe snapshot** for
open-ended exploration — only after the typed path is trusted.

---

## 6. What the analyst emits (typed proposals)

No prose-only conclusions. Every run emits one or more **pre-registered**
proposals from a fixed taxonomy.

### 6.1 Decision taxonomy

| # | Type | When | Routes to |
|---|---|---|---|
| 1 | **Failure-mode triage** | per bad decision | classifier (§4); not a tuner |
| 2 | **Counterfactual finding** | missed win / better later line under assumptions | evidence for 3–5; training note |
| 3 | **Weight-direction hypothesis** | feature mis-weighted | Texel/CMA-ES + SPRT |
| 4 | **New-feature proposal** | recurring loss has no capturing term | human-reviewed code + re-tune + gate |
| 5 | **Data-quality / coverage flag** | broken or under-sampled stats | collection, not tuning |
| 6 | **Goal / search-policy suggestion** | systematic GoalSet or beam miss | strategist prompts, scout settings, budgets — **not** inventing a new overlay mechanism (that already ships) |

Types 3–4 are the tuning core. Type 2 is the new high-value evidence channel.
Type 6 replaces the old “planner-bias suggestion → build an overlay” item: the
live Goal Strategist already owns overlays.

### 6.2 Proposal schema (pre-register the test)

```json
{
  "id": "hyp-2026-07-26-003",
  "type": "weight_direction",
  "target": "reactive_potential",
  "claim": "over-weighted; AI hoards ready runes for unused reactions",
  "direction": "decrease",
  "predicted_effect": "win rate rises when reactive_potential weight is lowered",
  "falsifiable_test": {
    "method": "cma_es_then_sprt",
    "metric": "selfplay_winrate_vs_baseline",
    "success": "SPRT accepts at +",
    "holdout": "validate on games not used to form the hypothesis"
  },
  "evidence": {
    "aggregate": "mean reactive_potential 2.7 in losses vs 1.1 in wins (n=240)",
    "example_games": [12, 19, 27],
    "counterfactuals": ["cf-12-t4", "cf-19-t6"],
    "effect_size": 0.34
  },
  "confidence": "medium",
  "risk": "correlated with runes_available; prefer joint refit"
}
```

**New-feature** proposals additionally carry: `feature_name`, `concept`,
`compute_sketch`, `expected_sign`, `implements_in` (`ScoreModel.build_score_features`),
`correlated_with`, `human_review_required: true`.

**Counterfactual findings** carry: snapshot key, root line, horizon, assumption
set, leaf predicates satisfied, comparison to played line.

---

## 7. Statistical guardrails (deterministic)

1. **Held-out split** — explore (form hypotheses) vs confirm (test). Pass only on
   confirm.
2. **Multiple-comparison correction** — Benjamini–Hochberg FDR (or Bonferroni
   for small N) on confirm-set tests.
3. **Effect size + n** on every aggregate; min-n gates (mirror card stats).
4. **Confounder surfacing** in the briefing (`cards_in_hand`↔`card_drawn`,
   `battlefield_control`↔`battlefields_conquered`,
   `reactive_potential`↔`runes_available`). Prefer **joint refit** over
   single-feature edits.
5. **Controls** — `went_first`, `origin`, `selector_source`, goals-on when logged.
6. **SPRT win-rate gate is final** for weight commits. LLM confidence is advisory.
7. **Assumption labels** — counterfactual wins without an assumption set are
   invalid evidence.

---

## 8. The loop

```
1. BUILD BRIEFING     Tier A from EXPLORE split only (§2.1)
2. ANALYZE            LLM + typed DB tools (§5); sample games (Tier C)
3. COUNTERFACTUALIZE  on swing / high-regret turns: same-turn search_for,
                      then optional short rollouts (§3)
4. TRIAGE             failure modes (§4) before any weight proposal
5. PROPOSE            ranked typed hypotheses (§6)
6. DEDUP / FILTER     drop repeats (hypotheses log); schema-validate; cap batch
7. VALIDATE           falsifiable_test on CONFIRM split; apply FDR (§7)
8. GATE               SPRT vs baseline for surviving weight/feature candidates
9. COMMIT / RECORD    accept → weight_versions (or feature PR); all attempts →
                      tuning_runs / hypotheses log
10. FEED BACK         next briefing includes previously tried + outcomes
```

### 8.1 New tables

- **`hypotheses`** — full §6.2 JSON, weight_version, explore/confirm split id,
  status (`proposed|validated|rejected|committed`), validator result.
- **`counterfactual_runs`** (optional, or embed under hypotheses evidence) —
  snapshot key, constraints/root, horizon, assumptions, leaf summary, tool
  latency.
- Link `tuning_runs` (storage doc) to `hypotheses.id` when that table lands.

---

## 9. Build order

1. ~~**Telemetry for goals/tools**~~ — **shipped:** GoalSet/overlay/achieved-at-leaf
   on `search_decisions`, compact Reasoner rows in `reasoner_decisions`,
   `turn_snapshots`.
2. **Deterministic briefing + typed DB tools** (§2.1, §5) wrapping existing
   reports — useful to humans with no LLM yet.
3. **Same-turn counterfactual** (§3.1) on logged snapshots via EngineServer.
4. **Failure-mode summary** (§4) as code over regret + counterfactual hits.
5. **Read-only LLM analyst** — emit typed hypotheses; measure confirm-set hit
   rate; do not auto-act.
6. **Multi-turn counterfactual** (§3.2) with hard horizon/assumption labels.
7. **Wire validator + SPRT** for weight-direction hypotheses (Texel already
   exists; CMA-ES + `tuning_runs` still open — Score_Tuning).
8. **`hypotheses` log + feedback-in-context** → iterative loop.
9. **New-feature proposals** with human code review (Score_Tuning §4).
10. Optional sandboxed code interpreter over a DB snapshot.

**Bottom line:** present schema + aggregates + a few games; query through typed
tools; use engine counterfactuals to find missed wins and later goals under
labeled assumptions; emit pre-registered hypotheses; let held-out validation and
self-play SPRT decide. The LLM’s edge is causal diagnosis and naming missing
concepts — not computing weights or asserting hidden-info certainty.

---

## 10. References

- OPRO — arXiv:2309.03409; Eureka — arXiv:2310.12931; FunSearch — Nature 2023
- Data Interpreter — arXiv:2402.18679; Chain-of-Table — arXiv:2401.04398
- Benjamini–Hochberg FDR — 1995, J. R. Statist. Soc. B
- Chess game review / MultiPV — Stockfish UCI; chess.com-style classification
- Hearthstone missed lethal / combat sim — LethalCue; HSReplay Bob’s Buddy
- TCG long-horizon failures — TCG-Bench (EACL 2026 Findings); PTCG-Bench
  arXiv:2605.29653
- RAP / ReAct tool loops — arXiv:2305.14992; arXiv:2210.03629 (pattern reuse
  for the analyst’s tool use, not a second live Reasoner)
