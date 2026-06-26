# LLM Data-Analysis & Hypothesis Loop — Design Doc

Status: design only (no code yet).
Scope: **how** the LLM inspects the telemetry, forms hypotheses, and proposes
weight changes / new features — i.e. the *interaction & data-presentation layer*.

Companion docs (read first):
- `Statistical_Analysis_Storage.md` — what data exists (schema, endpoints).
- `Score_Tuning_And_Evolution.md` — the *roles* the LLM plays (§3 hypotheses,
  §4 feature invention) and the optimizer math (Texel/CMA-ES). **This doc does
  not repeat those**; it specifies the concrete mechanics that doc left open:
  how the data reaches the model and what structured decisions come back.

The guiding principle from the tuning doc holds throughout:
**the LLM hypothesizes and explains; deterministic tooling decides.** This doc is
about making that division *operational*.

---

## 0. Why a dedicated interaction layer is needed

Three failure modes appear if you "just give the LLM the database":

1. **Context blow-up / numeric degradation.** Thousands of `search_decisions`
   rows won't fit, and even when a big table fits, LLM reasoning over many raw
   numeric rows degrades sharply. Table-reasoning research (Chain-of-Table,
   arXiv:2401.04398; Binder, arXiv:2210.02875) shows models do far better over
   *small, transformed* tables than over large raw ones. ⇒ never dump rows; feed
   **schema + aggregates + small slices**.

2. **Spurious correlations / p-hacking.** An LLM asked to "find what predicts
   winning" over ~30 features will happily report noise as signal. With many
   candidate hypotheses the false-discovery rate explodes (classic multiple-
   comparisons problem). ⇒ the LLM must **pre-register** each hypothesis and a
   deterministic validator must test it on **held-out** data.

3. **Ungrounded numbers.** LLMs are worse than Texel/CMA-ES at picking weight
   *values* (Score_Tuning §4.3). ⇒ the LLM emits *directions and structured
   proposals*, never final committed weights.

The whole design below exists to enforce those three constraints.

---

## 1. How data is presented to the LLM

Layered, from always-on context to on-demand pull. This mirrors how agentic
data-science systems (Data Interpreter, arXiv:2402.18679) separate a stable
*plan/context* from *tool-driven* data access.

### 1.1 Tier A — always in context (small, curated)
A compact **"analysis briefing"** assembled deterministically before the LLM
runs. Target ≤ ~2–3k tokens. Contents:

- **Schema card** — table names, columns, types, and one-line semantics for
  `search_decisions`, `candidate_lines`, `decision_snapshots`, `card_events`,
  `turn_snapshots`, `games`. (Schemas, not rows — this is what text-to-SQL
  research, Spider/BIRD, shows the model actually needs.)
- **Feature dictionary** — the ~30 scoring terms, each with its weight,
  sign, and one-line meaning (generated from `scoring_profile.json` +
  `Scoring_Features_Reference.md`). The LLM cannot reason about a feature it
  can't name.
- **Dataset summary stats** — n games, n decisions, win rate, date range,
  origin mix (`self_play`/`vs_human`/`vs_heuristic`), weight_version coverage.
- **Pre-computed headline aggregates** (the high-value views, as small markdown
  tables):
  - Feature impact table (from `feature_report.py`): per feature → in-play %,
    avg |impact|, net direction.
  - Feature→outcome correlation table: per feature → mean value in won vs lost
    decisions, plus a simple effect size (see §4).
  - Card stats table (from `card_report.py`), already min-N gated.

> Present these as **markdown tables**, not JSON or CSV. For the small tables we
> show the LLM (tens of rows), markdown is the most reliably parsed-and-reasoned
> format; JSON wastes tokens on punctuation and CSV loses the header alignment
> cue. Keep numbers rounded (3 sig figs) — false precision wastes tokens and
> doesn't help reasoning.

### 1.2 Tier B — on-demand, via a constrained query tool
The LLM can pull more, but **never writes raw SQL against the live DB**. Instead
it calls a typed, read-only analysis API (see §2). Results come back as small
markdown tables, capped at K rows (e.g. 30) with an explicit "N more not shown"
footer. This is the text-to-SQL safety pattern: a constrained, validated query
surface rather than arbitrary SQL (avoids both injection and the model writing
expensive/incorrect joins).

### 1.3 Tier C — qualitative drill-down (a few full examples)
For causal reasoning the LLM needs to *see* representative games, not just
aggregates — this is what turns "feature X correlates with losing" into a
trustable mechanism (Score_Tuning §3.1). Provide, on request, a **handful** of
fully-rendered decisions: the `decision_snapshot` (board state), the
`candidate_lines` with their `score_breakdown`, the chosen line, and the
eventual `game_outcome`. Cap at ~3–5 examples per request (token budget +
keeps reasoning focused). Sample them deliberately: e.g. "highest-regret
decisions in lost games," not random.

**Takeaway:** aggregates for *what*, a few concrete games for *why*. Never the
raw middle (thousands of rows).

---

## 2. How the LLM interacts with the data (the tool surface)

Two viable mechanisms; we recommend a **hybrid** matching the maturity ladder.

### 2.1 Recommended: a typed analysis-tool API (start here)
A small set of read-only, parameterized tools the LLM calls in a ReAct loop. Each
returns a small markdown table. Examples:

- `feature_outcome_stats(feature?, origin?, min_turn?, max_turn?, seat?)`
  → per-feature mean-in-wins vs mean-in-losses, effect size, n.
- `card_stats(sort, min_plays, origin?)` → wraps `card_report.py`.
- `feature_impact(sort, filters)` → wraps `feature_report.py`.
- `sample_decisions(filter, order_by, limit≤5)` → Tier-C drill-down rows.
- `slice_winrate(group_by, filters)` → win rate conditioned on a bucket
  (e.g. win rate when `reactive_potential ≥ 3` vs `< 3`).
- `cohort_compare(weight_version_a, weight_version_b)` → A/B summary.

Why start here: bounded, safe, cacheable, and each tool encodes a *correct*
statistical computation once (the LLM can't get the SQL subtly wrong). This is
the OPRO/Eureka discipline — the LLM orchestrates; the scoring/measurement is
deterministic code.

### 2.2 Later: sandboxed code interpreter over a dataframe
For open-ended exploration the LLM writes Python against a read-only snapshot
(pandas dataframe of the tables) in a sandbox — the Data Interpreter /
code-interpreter pattern (arXiv:2402.18679). More powerful (arbitrary
group-bys, plots, regressions) but needs a sandbox, resource limits, and output
truncation. Gate this behind the typed API working first.

**Consensus from the field:** prefer *pre-computed correct aggregates + a
constrained query tool* over free-form SQL for reliability; add the
code-interpreter only when you need exploratory flexibility, and still feed it a
**snapshot**, never the live DB.

---

## 3. What decisions the LLM makes (typed outputs)

The LLM never returns prose-only conclusions. Every analysis run emits one or
more **typed proposals** drawn from a fixed taxonomy. This is the OPRO/Eureka/
FunSearch structured-proposer pattern: constrain the model to a schema so the
output is machine-checkable and routable to a validator.

### 3.1 Decision taxonomy
| # | Decision type | When | Routes to |
|---|---|---|---|
| 1 | **Failure-mode triage** | per bad decision | classifier, not tuner (Score_Tuning §3.3) |
| 2 | **Weight-direction hypothesis** | a feature looks mis-weighted | Texel/CMA-ES + SPRT gate |
| 3 | **New-feature proposal** | a recurring loss has no term capturing it | human-reviewed code + re-tune + gate |
| 4 | **Data-quality / coverage flag** | a stat looks broken or under-sampled | back to data collection, not tuning |
| 5 | **Planner-bias suggestion** | a multi-turn pattern the per-turn search misses | `planner.py` overlay (Score_Tuning §5) |

Types 2–3 are the tuning core; 1 and 4 prevent tuning the wrong thing; 5 feeds
the cross-turn layer.

### 3.2 Proposal schema (every hypothesis is pre-registered)
The key anti-p-hacking move: the LLM must state the test *before* it's run, in a
structured form a validator can execute mechanically.

```json
{
  "id": "hyp-2026-06-25-003",
  "type": "weight_direction",          // taxonomy above
  "target": "reactive_potential",      // feature or weight key
  "claim": "over-weighted; AI hoards ready runes for reactions it never uses",
  "direction": "decrease",             // increase | decrease | sign_flip | n/a
  "predicted_effect": "win rate rises when reactive_potential weight is lowered",
  "falsifiable_test": {                // how the validator checks it — REQUIRED
    "method": "cma_es_then_sprt",      // or texel_refit | ab_selfplay | held_out_corr
    "metric": "selfplay_winrate_vs_baseline",
    "success": "SPRT accepts at +",
    "holdout": "validate on games not used to form the hypothesis"
  },
  "evidence": {
    "aggregate": "mean reactive_potential 2.7 in losses vs 1.1 in wins (n=240)",
    "example_games": [12, 19, 27],     // Tier-C drill-down the LLM cited
    "effect_size": 0.34
  },
  "confidence": "medium",
  "risk": "correlated with runes_available; refit may shift that instead"
}
```

A **new-feature proposal** (type 3) additionally carries:
```json
{
  "feature_name": "lethal_proximity",
  "concept": "rewards developing toward 8 points / lethal, not just current score",
  "compute_sketch": "victory_score - my_score, non-linear closeness; from leaf_snap",
  "expected_sign": "positive",
  "implements_in": "ScoreModel.build_score_features",
  "correlated_with": ["score_diff", "point_scored"],   // overfit watch
  "human_review_required": true
}
```

### 3.3 Why typed, pre-registered output matters
- **Routable**: a dispatcher sends each type to the right validator automatically.
- **Auditable**: every hypothesis + its test + its result is a row (see §5),
  so you can later ask "what % of LLM hypotheses validated?" — a direct check on
  whether the LLM is finding signal or noise.
- **Anti-p-hacking**: the `falsifiable_test` + `holdout` fields force the
  proposal to commit to a test on data it didn't see, which is the standard
  defense against the multiple-comparisons inflation a free-form LLM analysis
  would cause.

---

## 4. The statistical guardrails (deterministic, not LLM)

These run as code around the LLM, because the LLM is the *source* of the
p-hacking risk, not its mitigation.

1. **Held-out split.** Partition games into *explore* (LLM forms hypotheses) and
   *confirm* (validator tests them). A hypothesis only "passes" if it holds on
   confirm data. Pre-register before peeking at confirm (the §3.2 schema enforces
   this by construction).
2. **Multiple-comparison correction.** When the LLM emits N hypotheses in a
   batch, apply Benjamini–Hochberg FDR (or Bonferroni for small N) to the
   confirm-set tests. Report adjusted significance, not raw.
3. **Effect size + n, always.** Every aggregate shown to the LLM and every test
   carries its sample size and an effect size (e.g. standardized mean diff), so
   "significant but tiny" is visible. Gate per-feature claims behind a min-n
   (mirrors `card_stats` min-plays).
4. **Confounder surfacing.** The briefing explicitly lists known correlated
   feature pairs (`cards_in_hand`↔`card_drawn`, `battlefield_control`↔
   `battlefields_conquered`, `reactive_potential`↔`runes_available`) so the LLM
   is warned, and the validator prefers a **joint refit** (Texel/CMA-ES over all
   weights) over single-feature edits — a single-feature change often just
   displaces signal onto its correlate.
5. **Initiative / origin controls.** Use the `went_first` and `origin` columns
   as covariates or stratifiers so the LLM isn't shown win-rate gaps that are
   really first-player or opponent-pool artifacts.
6. **The win-rate gate is final.** No hypothesis becomes a committed weight
   without the self-play SPRT gate from Score_Tuning §2.3. The LLM's confidence
   field is advisory only.

---

## 5. The loop (putting it together)

Mirrors the idea→experiment→analysis→iterate loops of automated-discovery
systems (The AI Scientist, arXiv:2408.06292; Google AI co-scientist's
generate-debate-evolve; Coscientist, Boiko et al., Nature 2023), specialized to
weight tuning:

```
1. BUILD BRIEFING   deterministic: assemble Tier-A context (§1.1) from current
                    DB + weight_version, on the EXPLORE split only.
2. ANALYZE          LLM reads briefing, calls analysis tools (§2) to drill in,
                    samples a few games (Tier C) for causal grounding.
3. PROPOSE          LLM emits a ranked list of typed, pre-registered hypotheses
                    (§3 schema). Rank by expected win-rate impact × confidence.
4. DEDUP / FILTER   deterministic: drop hypotheses already tried (query the
                    hypotheses log), enforce schema validity, cap batch size.
5. VALIDATE         deterministic: run each falsifiable_test on the CONFIRM split
                    (Texel refit / CMA-ES / A-B self-play); apply FDR (§4).
6. GATE             SPRT win-rate vs baseline for surviving candidates.
7. COMMIT / RECORD  accept → new weight_versions row (or human-reviewed feature
                    PR for type 3). Every attempt → tuning_runs / hypotheses log.
8. FEED BACK        append (hypothesis → outcome) to the log; next iteration's
                    briefing includes "previously tried" so the LLM doesn't
                    repeat itself and can build on what worked (OPRO-style
                    trajectory-in-context, arXiv:2309.03409).
```

Step 8 is what makes it a *learning* loop rather than one-shot analysis: the LLM
sees the running ledger of what it proposed and whether the simulator confirmed
it — the same "show prior (solution,score) pairs" mechanism OPRO/Eureka use to
improve proposals over iterations.

### 5.1 New tables this loop needs (extends storage doc)
- **`hypotheses`** — one row per LLM proposal: the full §3.2 JSON, the
  weight_version it was formed against, explore/confirm split id, status
  (proposed|validated|rejected|committed), and the validator's measured result.
  This *is* the audit trail and the "don't repeat" memory.
- (`tuning_runs` from the storage doc already records the weight-delta + SPRT
  verdict; link each to its `hypotheses.id`.)

---

## 6. Maturity ladder (build order)

1. **Deterministic briefing generator** (§1.1) + the read-only analysis tools
   (§2.1). No LLM yet — just produce the markdown the human currently reads.
2. **`feature_outcome_stats` + held-out split + FDR** (§4) as plain code. This
   alone is useful (it's Texel-adjacent diagnosis) and is the validator the LLM
   will later call.
3. **LLM analyst, read-only.** Feed briefing + tools; have it emit typed
   hypotheses (§3) — but only *report* them, don't auto-act. Measure: what
   fraction validate on confirm data? This calibrates trust before any
   automation.
4. **Wire the validator + SPRT gate** so accepted weight-direction hypotheses
   flow to Texel/CMA-ES automatically (Score_Tuning pipeline).
5. **`hypotheses` log + feedback-in-context** (§5 step 8) → iterative loop.
6. **New-feature proposals** (type 3) with human-reviewed code gate
   (Score_Tuning §4).
7. **Sandboxed code interpreter** (§2.2) for open-ended exploration, once the
   typed path is trusted.

**Bottom line:** present **schema + aggregates + a few concrete games**, never
raw rows; let the LLM **query through a typed read-only tool**, not free SQL;
make it emit **typed, pre-registered, falsifiable hypotheses**; and let
**deterministic held-out validation + the self-play win-rate gate decide**. The
LLM's edge is naming missing concepts and explaining *why* a weight is wrong —
not computing the numbers.

---

## 7. References
- The AI Scientist — Lu et al., arXiv:2408.06292 — https://arxiv.org/abs/2408.06292
- Google "Towards an AI co-scientist" — https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/
- Coscientist (autonomous chemical research) — Boiko et al., Nature 2023 — https://www.nature.com/articles/s41586-023-06792-0
- Data Interpreter (LLM agent for data science) — arXiv:2402.18679 — https://arxiv.org/abs/2402.18679
- Chain-of-Table (table reasoning) — arXiv:2401.04398 — https://arxiv.org/abs/2401.04398
- Binder (binding language models to tables/programs) — arXiv:2210.02875 — https://arxiv.org/abs/2210.02875
- Spider text-to-SQL — https://yale-lily.github.io/spider ; BIRD — https://bird-bench.github.io/
- OPRO "LLMs as Optimizers" (trajectory-in-context proposer) — arXiv:2309.03409 — https://arxiv.org/abs/2309.03409
- Eureka (LLM reward design + reflection) — arXiv:2310.12931 — https://arxiv.org/abs/2310.12931
- FunSearch — Nature 2023 — https://github.com/google-deepmind/funsearch
- Benjamini–Hochberg FDR — Benjamini & Hochberg, 1995, J. R. Statist. Soc. B
