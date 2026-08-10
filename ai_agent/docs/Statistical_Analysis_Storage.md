# Statistical Analysis Storage — Design Doc

Status: **core tuning dataset + goal/Reasoner/turn telemetry implemented**
(`memory.py` / `capture.py`); `tuning_runs` and `hypotheses` are still open.
Scope: queryable data storage for analysis/tuning of the search + linear-eval AI
(including goal overlays and Reasoner decisions).

Post-game analyst plan: `LLM_Data_Analysis_Loop.md`. Weight-tuning algorithms:
`Score_Tuning_And_Evolution.md`.

## Context: the AI being analyzed

- **`Scripts/Game/TurnSearch.gd`** — beam search over `LegalMoveEnumerator`;
  simulates lines to quiescence; emits top-N candidate lines with `features` +
  `score_breakdown`.
- **`Scripts/Game/ScoringProfile.gd` + `Data/AI/scoring_profile.json`** — linear
  weighted-sum eval via `ScoreModel.build_score_features` → per-term
  `score_breakdown` (exact additive attribution; no SHAP needed). Optional
  transient GoalSet overlay (`RIFTBOUND_GOALS`).
- **Line selection** — `choose_line` (LLM), argmax (`RIFTBOUND_SEARCH_ARGMAX`),
  or single-line short-circuit. Strategist may bias generation/selection; a
  future Reasoner may commit lines directly
  (`Deliberative_Reasoning_Toolkit.md`).
- Live investigation tools: `search_for` / `simulate` / `deepen` via
  `EngineServer` (Phases 0–2 done).

## Goal of the data layer

Capture enough structured, queryable data to drive:
1. **Credit assignment** — which moves had the biggest +/- impact.
2. **Eval weight tuning** — which features are mis-weighted (Texel / CMA-ES).
3. **Failure-mode separation** — selection vs search vs eval, plus goal /
   investigation / horizon misses when those modes are on
   (`LLM_Data_Analysis_Loop.md` §4).
4. **Per-card statistics** — play/draw rates and impact.
5. **Counterfactual review** — restore `decision_snapshots` for offline
   `search_for` / short rollouts.

Core triad (always):
- **Selection error** — better line in top-N (`regret > 0`), selector picked another.
- **Search error** — realized-best / counterfactual win never in beam.
- **Eval error** — best line generated but mis-scored (weight/feature target).

---

## 1. What is stored (`ai_agent/agent_memory.db`, see `memory.py`)

Schema is created on startup (`CREATE TABLE IF NOT EXISTS`). Default path is
overridable via `RIFTBOUND_DB_PATH` (self-play often uses `ai_agent/selfplay.db`).

### 1.1 Decision / reliability tables (pre-search agent)

| Table | Grain | Key contents |
|---|---|---|
| `decisions` | per AI decision | turn, decision_type, `brief_state_hash`, reasoning, `move_json`, accepted, rejection_reason |
| `opponent_actions` | per visible opp action | turn, action text |
| `games` | per finished game | outcome, scores, turns, `first_player_index`, seed |
| `decision_eval_metrics` | per decision | model calls, retries, latency, token usage (planner/actor) |
| `client_decision_metrics` | per decision | engine latency, rejection retries, heuristic fallback |
| `game_eval_summary` | per game | aggregated reliability scorecard |
| `human_feedback` / `move_feedback` | reviewer | rubric / like-dislike |

### 1.2 Tuning dataset (search mode — **shipped**)

Captured when `RIFTBOUND_SEARCH=on` via `capture.py` (live `/decision` or offline
self-play import). Details in §2.

| Table | Grain |
|---|---|
| `search_decisions` | per searched decision (features, breakdown, regret, origin, selector, outcome backfill, GoalSet/overlay/achieved-at-leaf) |
| `candidate_lines` | per candidate per decision |
| `decision_snapshots` | full BriefState + scalars at decision |
| `weight_versions` | profile hash/json + git SHA |
| `card_events` | per card lifecycle event (base `definition_id` stamped) |
| `reasoner_decisions` | per `/reason` (compact investigation summary + tool_mix/budget) |
| `turn_snapshots` | per completed turn per AI seat (scalars + rune counts + BriefState) |

**Still missing for full analysis:** `tuning_runs`, `hypotheses`.

---

## 2. Tuning tables (schema reference)

### A. `search_decisions` — core tuning dataset (one row per searched decision)
- `id` PK
- `game_id, turn, decision_index, decision_type, mode` (main|reactive)
- `my_player_index` — deciding seat (self-play separation)
- `chosen_line_id`
- `chosen_line_score`, `best_candidate_score`
- `regret` = best − chosen
- `score_margin` = best − 2nd-best
- `chosen_breakdown_json` — per-term `score_breakdown`
- `chosen_features_json` — raw `build_score_features` dict (**shipped** on
  `CandidateLine.features`; required for Texel — do not reverse from breakdown at
  weight = 0)
- `num_candidates`
- `search_stats_json` — nodes/branches/beam/elapsed/stopped_reason
- `selector_source` (`llm`|`fallback`|`argmax`|`single`), `selector_reasoning`
- `origin` (`self_play`|`vs_human`|`vs_heuristic`)
- backfilled at game end: `game_outcome`, `final_score_diff`, `went_first`
- `weight_version_id` FK → `weight_versions`
- `timestamp`

### B. `candidate_lines` — one row per candidate per decision
Lets you detect search vs eval vs selection error and ask "was the realized-best
line even generated?"
- `id` PK, `search_decision_id` FK
- `line_id`, `rank`, `score`, `chosen` (bool)
- `moves_json`, `breakdown_json`, `features_json`, `resolved_state_json`

### C. `decision_snapshots` — full queryable state at each decision
Replaces hash-only. Store compact normalized `BriefState` JSON + extracted scalar
columns for fast SQL filtering without JSON parsing.
- `id` PK, `game_id, turn, decision_index`
- scalars: `my_score, opp_score, my_energy, board_might_diff, cards_in_hand,
  cards_in_hand_opp, bf_control_net`
- `brief_state_json` (full compact snapshot)

### D. Game-end backfill (mechanism, not a table)
On `/game_over`: `UPDATE search_decisions SET game_outcome=?, final_score_diff=?
WHERE game_id=?`. Single most important wiring step — without it the tuner has no
label on its feature vectors.

**Also record who went first.** A binary `game_outcome` silently bakes
first-player initiative into every tuned weight. Store turn order so the tuner can
control for it:
- `games.first_player_index` (which seat took turn 1) and per-row
  `search_decisions.went_first` (was the deciding seat the first player).
- This makes initiative a controllable covariate (filter, stratify, or add it as a
  feature) instead of hidden bias, and complements the paired-seed / swapped-seat
  variance reduction in the self-play section. `/game_over` already knows the seats;
  emit the starting seat alongside winner/scores/turns.

### E. Supporting tables
- **`turn_snapshots`** — per turn: score, board might, card/rune counts, bf
  control → win-probability curves, swing-turn detection, WPA basis for cards.
- **`weight_versions`** — `id`, `profile_hash`, `profile_json`, `git_sha`,
  `created_at`. Every result attributable to a profile version (essential for A/B).
- **`tuning_runs`** — proposed weight delta, validation match results (win-rate,
  SPRT verdict), accepted/rejected, parent/child `weight_version_id`.

---

## 3. Per-card statistics

### Join key
`GameState.allocate_instance_id(definition_id)` (`Scripts/Domain/GameState.gd`)
returns `definition_id` for the first copy and `definition_id-N` (N≥2) afterward.
The aggregation key across instances and games is the base `definition_id`.

**⚠ Do NOT reverse it by regex-stripping a trailing `-<digits>`.** That rule
(`-\d+$`) corrupts any definition whose id legitimately ends in `-<number>`, and
makes a 2nd-copy instance (`garen-2`) collide with a hypothetical definition named
`garen-2`. The strip is lossy and ambiguous. **Instead, carry the base
`definition_id` explicitly** on the instance at allocation time and stamp it onto
every `card_event` row, rather than deriving it from `instance_id`. (If a strip is
ever unavoidable, only strip the counter the allocator itself appended, not any
`-N` present in the original `definition_id`.)

### Event capture — `card_events` (one row per card lifecycle event)
- `game_id, turn, card_def_id, instance_id`
- `event` ∈ {drawn, played, discarded, died, mulliganed, scored,
  left_in_hand_at_end, in_opening_hand}
- `energy_spent`
- `breakdown_delta_json` — the decision's `score_breakdown` contribution when the
  card resolved (free attribution thanks to linear eval)

### Derived view — `card_stats`
**Frequency / tempo**
- draw rate = seen / games
- play rate = played / games
- **play-when-drawn rate = played / drawn** (flags dead/situational cards)
- mulligan rate
- avg turn played (curve position)
- stuck-in-hand rate = held at game end / drawn

**Impact**
- win-rate-when-played vs base win rate (naive; survivorship-biased)
- **WPA / win-rate-added** — Δ win-probability of the turn it was played, from
  `turn_snapshots` (TCG analog of chess centipawn-loss; the honest impact metric)
- avg `score_breakdown` contribution the turn it resolved
- points/conquers contributed, units killed, own deaths, avg might swing
- survival rate (turns alive after play)
- trade efficiency = enemy might killed ÷ own might lost

**Quality / reliability**
- rejection / illegal-attempt rate per card (rules the AI mishandles)
- like/dislike sentiment join from `move_feedback`

### Caveats
1. **Survivorship/selection bias** — "win-rate when played" is confounded by the
   AI choosing good spots; prefer WPA and breakdown-contribution.
2. **Sample size** — gate per-card rates behind min-N (e.g. ≥20 plays) before
   trusting them.

---

## One game vs many games

- **Single-game** analysis → localization + qualitative diagnosis (top-3 swing
  decisions, debugging search/eval). Never auto-commit weights from one game.
- **Cross-game statistics (≈50–200+ games)** → drive actual weight changes. A
  weight is a global parameter; TCG variance (shuffle, hidden info, opponent
  policy) makes per-game signal-to-noise too low. Require each tuned feature to
  appear many times with both win and loss outcomes.

---

## Data-source notes (where each field comes from)

- `chosen_breakdown_json`, `chosen_features_json`, candidate set, `search_stats`:
  computed in Godot (`TurnSearch` / `ScoreModel`), sent on
  `DecisionRequest.candidate_lines` (including `features`), persisted by
  `capture.py` at `/decision` (or offline import).
- `decision_snapshots`: from `request.brief_state` (full JSON + extracted scalars).
- `card_events`: emitted from Godot and stored with base `definition_id` (see §3
  join-key note); do not reverse from `instance_id`.
- `game_outcome` / `went_first` / `first_player_index`: `/game_over` backfill
  (seat-aware for two-seat self-play under one `game_id`).
- GoalSet / overlay / achieved-at-leaf: threaded from `/goals` or `/reason`
  caches into `capture_search_decision` → `search_decisions` columns
  (`goals_source`, `goal_set_json`, `overlay_json`, `chosen_overlay_delta`,
  `chosen_goal_achieved_json`). Still mirrored to `agent_search.log` when
  `RIFTBOUND_LOG_INPUTS=1`.
- Reasoner investigation summary: `capture_reasoner_decision` on `/reason` →
  `reasoner_decisions` (compact `tool_mix` / budget / flags). Compact
  `tool_trace` is also attached to the `/reason` telemetry payload for eval.
- `turn_snapshots`: Godot `turn_ended` → `POST /turn_snapshot` (and offline
  JSONL kind `turn_snapshot`) at end of Ending Phase before `turn_number++`.

---

## Self-play & argmax data generation

Cross-game tuning needs volume (50–200+ games) and speed. A human in the loop
makes that impossible, and the LLM `choose_line` round-trip is the dominant
per-decision cost (network + tokens) while `TurnSearch` is ~250 ms local. Two
levers solve both.

### Run modes
| Mode | Both seats | Selector | Use |
|---|---|---|---|
| **argmax-only** | search + scoring | take top-scored line, **no LLM call** | bulk data gen, weight tuning |
| **LLM-selector** | search + scoring | `choose_line` (current behaviour) | end-to-end quality measurement |
| **asymmetric A/B** | seat A = candidate weights, seat B = baseline | either | validate a proposed weight delta |

### Argmax mode (skip the LLM)
- The fallback in `agent.py::choose_line` already is argmax:
  `best = max(candidate_lines, key=lambda l: l.score)`. So this is a short-circuit,
  not new logic.
- Gate behind an env flag mirroring `RIFTBOUND_SEARCH`, e.g.
  `RIFTBOUND_SEARCH_ARGMAX=on` → return the top line without the model round-trip.
- Fastest variant: `candidate_lines` are returned score-sorted by
  `TurnSearch._build_candidate_lines`, so `AIPlayer.gd` can pick `candidate_lines[0]`
  **entirely engine-side, never calling the agent server**. Best for bulk loops.
- **What it measures:** the search + weights in isolation (pure policy = the eval
  function). This is exactly right for weight tuning. It removes the LLM's
  judgement on contested `opponent_windows`, so: **tune weights in argmax mode;
  measure end-to-end quality with the LLM selector on.** The `selector_source`
  column in `search_decisions` keeps the two regimes separable.

### AI-vs-AI (self-play)
- Both seats run `TurnSearch` + `ScoringProfile`; infra is already seat-agnostic
  (`AIPlayer.gd` takes `player_index`, search/scoring use `_ai_index`).
- Run headless via `TcgTestRunner.gd`. Log a **deck/shuffle seed per game** into
  `games` for reproducibility and **paired-seed** variance reduction (same
  shuffle, swapped weights/seats).
- Always include a **fixed reference opponent** (current baseline profile, or the
  old heuristic `AIPlayer`) so improvements are anchored, not just relative.

---

## Concern: does self-play data match real human gameplay?

Valid and well-known. Self-play data is drawn from the **AI's own state
distribution**, which can diverge from the states humans steer into
(*distribution / covariate shift*). If the AI never reaches positions a human
would, its weights are untuned there. This is the single biggest validity risk of
a self-play tuning loop.

### How other projects handle it

- **Chess/Go engines (Stockfish, Leela, AlphaZero):** mostly accept self-play as
  the target — they optimise for strength vs *any* strong opponent, and the
  superhuman bar makes "match humans" moot. Their key trick is **opponent and
  position diversity** so the policy can't overfit one style: large randomised
  **opening books**, temperature/Dirichlet-noise exploration in early plies, and
  validation against *different* engine versions, not just self-mirrors.
- **Texel / fishtest tuning:** tune on positions sampled from **real games**
  (incl. human/online games), not only engine self-play, precisely to keep the
  training distribution near the deployment distribution.
- **Poker (Libratus/Pluribus) & hidden-info games:** self-play converges toward
  equilibrium, but they explicitly test against **humans and diverse opponent
  pools** before trusting results, because exploitable human tendencies live
  off-equilibrium.
- **Imitation/RL robotics (the DAgger lesson):** the canonical fix for covariate
  shift is to **mix in data from the deployment distribution** and iterate, rather
  than training purely on the policy's own rollouts.

### Practical mitigations for this project
1. **Opponent diversity, not just mirror self-play.** Pit search-AI vs the old
   heuristic `AIPlayer`, vs older weight versions, and vs deliberately skewed
   profiles (hyper-aggressive, hoarding, passive). Prevents overfitting one style.
2. **Deck/matchup diversity.** Rotate decks and seeds; a profile good only in the
   mirror is overfit.
3. **Anchor to human data where it exists.** `decision_snapshots` from
   human-vs-AI games (and `human_feedback` / `move_feedback`) are gold — use them
   as a **held-out validation set**: tune on self-play, but check the eval still
   ranks lines sensibly on human-reached positions. Tag rows with an
   `origin` field (`self_play` | `vs_human` | `vs_heuristic`) so the two
   populations never get silently mixed.
4. **Sanity-anchor the metric.** Final acceptance via win-rate vs a *fixed
   reference* + SPRT, plus a spot-check against human-game positions — not just
   "beats its own previous self."
5. **Exploration in data gen.** A little softmax/temperature over candidate
   scores (instead of strict argmax) during *data collection* widens the visited
   state distribution and reduces self-play tunnel vision. Keep strict argmax for
   *evaluation*.

**Bottom line:** self-play is the correct engine for volume, and the distribution
gap is real but routinely managed — diversify opponents/decks, keep a fixed
reference anchor, and reserve human-game snapshots as a held-out validation set.
The schema supports this via a per-row `origin` tag and `weight_versions`
attribution.

---

## Suggested build order

**Done**
0. `CandidateLine.features` + raw `build_score_features` emission; base
   `definition_id` on card events.
1. `weight_versions` + per-seat profile attribution.
2. `search_decisions` + `candidate_lines` + `decision_snapshots` (`selector_source`,
   `origin`, `went_first`, `chosen_features_json`).
3. `/game_over` backfill (`game_outcome`, `final_score_diff`, `first_player_index`).
4. `card_events` + `card_report.py` / `card_stats` aggregates (WPA still needs
   `turn_snapshots`).
5. Argmax short-circuit + headless self-play (`SelfPlaySim`) + offline JSONL
   capture / `import_selfplay_logs.py`.
6. Texel proposer (`texel_tune.py`) + `feature_report.py`.

**Done (telemetry gaps)**
7. Persist GoalSet + overlay deltas + achieved-at-leaf on `search_decisions`;
   compact Reasoner summary in `reasoner_decisions` (+ `tool_trace` on telemetry).
8. `turn_snapshots` via `/turn_snapshot` + self-play JSONL import.

**Open (next for post-game analysis)**
9. `tuning_runs` + SPRT gate records.
10. `hypotheses` (+ optional `counterfactual_runs`) for the analyst audit trail.
