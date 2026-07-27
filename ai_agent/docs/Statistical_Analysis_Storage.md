# Statistical Analysis Storage — Implementation Reference

Status: implemented core storage for search decisions, candidate lines, decision
snapshots, weight-version attribution, game-outcome backfill, and card lifecycle
events. Remaining planned pieces are called out below.

Scope: queryable data storage for analyzing and tuning the search +
linear-evaluation AI.

## Context: the AI being analyzed

- **`Scripts/Game/TurnSearch.gd`** — beam search over `LegalMoveEnumerator`
  moves; simulates each line to quiescence; emits top-N candidate lines. Defaults
  are beam 8, node budget 80, depth 6, and 250 ms, with callers overriding these
  for main-turn, scout, and Reasoner searches.
- **`Scripts/Game/ScoringProfile.gd` + `Data/AI/scoring_profile.json`** — a **linear
  weighted-sum** evaluation. Feature dict from
  `ScoreModel.build_score_features(root_snap, leaf_snap, steps)` (static func in
  `Scripts/Game/ScoreModel.gd`) → weighted sum + **per-term
  `score_breakdown`**. A dominating `win_game=1000` term with a shaping clamp.
- **`ai_agent/agent.py::choose_line`** — LLM demoted to a **policy selector** over
  engine-scored lines (returns `chosen_line_id`).
- Because eval is **linear**, `score_breakdown` is already an exact additive
  per-feature attribution — no SHAP/ablation needed.

## Goal of the data layer

Capture enough structured, queryable data to drive:
1. **Credit assignment** — which moves had the biggest +/- impact.
2. **Eval weight tuning** — which features are mis-weighted (Texel-style logistic
   regression of eval→outcome; TDLeaf-style leaf error).
3. **Failure-mode separation** — distinguish selection error vs search error vs
   eval error (see below).
4. **Per-card statistics** — play/draw rates and impact.

Three failure modes the schema must keep distinguishable:
- **Selection error** — best line was in top-N but the LLM picked another
  (`regret > 0` with a better candidate present).
- **Search error** — the realized-best line was never generated into top-N. No
  weight change fixes this; tune beam/depth/budget.
- **Eval error** — best line was generated but mis-scored. Only this one is fixed
  by weight tuning.

---

## 1. Existing reliability / feedback storage (`ai_agent/agent_memory.db`)

> **Note:** `agent_memory.db` has already been deleted, so there is no legacy data
> to migrate or preserve. The database rebuilds fresh from `CREATE TABLE` on next
> startup — new tuning tables/columns can be added directly to the schema without
> `ALTER TABLE` migration steps. (Tables below describe the schema the rebuilt DB
> recreates, not surviving data.)

| Table | Grain | Key contents | Gap for tuning |
|---|---|---|---|
| `decisions` | per AI decision | turn, decision_index, decision_type, `brief_state_hash` (HASH ONLY), reasoning, `move_json`, accepted, rejection_reason, outcome_summary | state not reconstructable; no features/breakdown |
| `opponent_actions` | per visible opp action | turn, action text | — |
| `games` | per finished game | outcome, my_score, opp_score, turns_played, `first_player_index`, seed | game-grain label and initiative metadata |
| `decision_eval_metrics` | per decision | model calls, retries, latency, token usage (planner/actor split) | reliability only, not quality |
| `client_decision_metrics` | per decision | engine latency, rejection retries, heuristic fallback | — |
| `game_eval_summary` | per game | aggregated reliability scorecard | — |
| `human_feedback` | reviewer | rubric scores, tags, note | — |
| `move_feedback` | per move | like/neutral/dislike sentiment | — |

The tuning-specific data that used to be missing from this table set is now
captured in the tables below. Still not implemented: `turn_snapshots`,
`tuning_runs`, and WPA-style card impact.

---

## 2. Implemented tuning tables

### A. `search_decisions` — core tuning dataset (one row per searched decision)
- `id` PK
- `game_id, turn, decision_index, decision_type, mode` (main|reactive)
- `chosen_line_id`
- `chosen_line_score`, `best_candidate_score`
- `regret` = best − chosen
- `score_margin` = best − 2nd-best
- `chosen_breakdown_json` — per-term `score_breakdown`
- `chosen_features_json` — flat `build_score_features` dict (Texel/regression input).
  `CandidateLine.features` is emitted by `TurnSearch._build_candidate_lines` and
  persisted directly; do not reconstruct it from `score_breakdown`.
- `num_candidates`
- `search_stats_json` — nodes_explored, branches, transposition_hits,
  max_depth_reached, beam_width, elapsed_ms, stopped_reason
- `selector_source` (`llm`|`fallback`|`argmax`), `selector_reasoning`
- `origin` (`vs_human` by default; `self_play` and `vs_heuristic` are supported)
- `my_player_index` — deciding seat for self-play separation
- backfilled at game end: `game_outcome`, `final_score_diff`
- `went_first` — was the deciding seat the first player this game (controls for
  initiative bias in tuning)
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
On `/game_over`, `capture.capture_game_over()` records the game result and calls
`Memory.backfill_game_outcome()` so every `search_decisions` row for the game gets
`game_outcome`, `final_score_diff`, and seat-aware `went_first`.

**Always record who went first.** A binary `game_outcome` silently bakes
first-player initiative into every tuned weight. Store turn order so the tuner can
control for it:
- `games.first_player_index` (which seat took turn 1) and per-row
  `search_decisions.went_first` (was the deciding seat the first player).
- This makes initiative a controllable covariate (filter, stratify, or add it as a
  feature) instead of hidden bias, and complements the paired-seed / swapped-seat
  variance reduction in the self-play section.

### E. Supporting tables
- **`weight_versions`** — implemented: `id`, `profile_hash`, `profile_json`,
  `git_sha`, `created_at`. Every result is attributable to the profile version
  that produced it; per-request profile JSON lets two self-play seats register
  different versions in the same run.
- **`turn_snapshots`** — planned: per turn score, board might, card/rune counts,
  bf control -> win-probability curves, swing-turn detection, WPA basis for cards.
- **`tuning_runs`** — planned: proposed weight delta, validation match results
  (win-rate, SPRT verdict), accepted/rejected, parent/child `weight_version_id`.

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

### Event capture — `card_events` (implemented; one row per card lifecycle event)
- `game_id, turn, card_def_id, instance_id`
- `event` ∈ {drawn, played, discarded, died, mulliganed, scored,
  left_in_hand_at_end, in_opening_hand}
- `my_player_index`
- `energy_spent`
- `breakdown_delta_json` — the decision's `score_breakdown` contribution when the
  card resolved (free attribution thanks to linear eval)

`GameController.card_event` is forwarded by `Scripts/AI/AIPlayer.gd` to
`POST /card_event`, and `Memory.record_card_event()` validates event names before
inserting. `/card_stats?min_plays=N` returns aggregate card statistics; WPA is not
included yet because `turn_snapshots` are still planned.

### Derived report — `/card_stats`
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

- `chosen_breakdown_json`, `chosen_features_json`, candidate set, and
  `search_stats`: computed in Godot (`TurnSearch` / `ScoreModel`), serialized on
  `CandidateLine`, and captured from `DecisionRequest.candidate_lines` by
  `capture.capture_search_decision()`.
- `decision_snapshots`: from `request.brief_state`, with fast-filter scalar
  columns extracted by `capture.snapshot_scalars()`.
- `card_events`: emitted by `GameController.card_event`, forwarded by
  `AIPlayer._on_card_event()`, and persisted through `/card_event`.
- `game_outcome` backfill: `/game_over` sends winner/scores/turns plus
  `first_player_index`; the capture layer sets `went_first` by comparing that to
  each row's `my_player_index`.

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
- Gate behind `RIFTBOUND_SEARCH_ARGMAX=on` -> return the top line without the
  model round-trip.
- Fastest variant: set `RIFTBOUND_SELFPLAY_CAPTURE` so `AIPlayer.gd` chooses the
  local argmax, logs the full server-bound payload to JSONL, and never calls the
  agent server. Replay the log with `ai_agent/import_selfplay_logs.py`; the
  importer uses the same `capture.py` helpers as the live endpoint.
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

## Implemented vs. remaining

Implemented:
1. `CandidateLine.features` and `search_state` emitted by `TurnSearch`.
2. `weight_versions` registration on server start and per-request profile
   attribution.
3. `search_decisions` + `candidate_lines` + `decision_snapshots` captured in
   `/decision`, including `selector_source`, `origin`, seat, and raw features.
4. Game-end backfill in `/game_over` (`game_outcome`, `final_score_diff`, and
   `first_player_index` -> `went_first`).
5. `card_events` capture and `/card_stats` aggregate report.
6. Argmax short-circuit, headless self-play, and offline JSONL capture/import.

Remaining:
1. `turn_snapshots` for swing-turn and WPA-style card impact.
2. `tuning_runs` metadata once the tuner/validation loop is formalized.
3. Optional exploration policy during data generation (softmax/temperature over
   candidate scores) if strict argmax proves too narrow for training data.
