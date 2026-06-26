# Score Tuning & Evolution — Design Doc

Status: design only (no code yet)
Scope: how to **tune** `Data/AI/scoring_profile.json` weights, **evolve** them over
many games, use an **LLM to propose hypotheses and design new features**, and
handle **delayed-value** (beyond-horizon) moves.

Companion doc: `Statistical_Analysis_Storage.md` covers **collecting** the data
(schema, endpoints, card stats). This doc covers **using** that data to improve
the evaluation. Read that one first for table/field names referenced here.

---

## 0. The system being tuned (recap)

- `ScoringProfile.gd` = **linear weighted sum** of features from
  `ScoreModel.build_score_features(root_snap, leaf_snap, steps)` (a static func in
  `Scripts/Game/ScoreModel.gd` — NOT a method on `MoveSimulator`), plus a
  dominating `win_game=1000` terminal term with a shaping clamp. Emits a per-term
  `score_breakdown`.
- `TurnSearch.gd` = beam search (beam 8, depth 6, node budget 80, 250 ms) over a
  **single turn**, scoring leaves with the profile.
- Linearity ⇒ `score_breakdown` is an **exact additive per-feature attribution**.
  This is the lever for everything below.

Tunable surface (`scoring_profile.json`): `win_game`, `state_weights`,
`action_weights`, `keyword_weights`, `battlefield_weights`, `end_of_turn`. ≈25–30
scalar weights today.

---

## 1. The horizon problem (delayed-value analysis)

The AI plans one turn because planning further requires guessing the opponent's
hidden hand and the AI's own unknown future draws — branching explodes. This is
the classic **horizon problem**. "Delayed impact" is really TWO problems:

1. **Delayed evaluation** — a move's payoff lands beyond the depth-6 / one-turn
   horizon (early cost, late win).
2. **Delayed credit assignment** — when tuning, how to reward the turn-3 setup
   that caused the turn-8 win.

### 1.1 Don't fix it by searching deeper
Verified from the CCG literature (LOCM): strong agents are **shallow search +
strong eval**, often 1-ply greedy. Hidden hands + unknown draws make deep
multi-turn search intractable and noisy. The intelligence belongs in the **leaf
evaluation**, not the tree depth. Our within-turn depth-6 is already generous.

### 1.2 Fix #1 — put delayed value INTO the eval as features
A static eval's whole job is to estimate *future* value without searching there.
Card advantage (Forge's `5*myCards - 4*theirCards`) is literally a delayed-value
feature — extra cards help turns later. Our current features are mostly
*immediate* (might on board, points scored, kills). The gap is **tempo /
development / setup** features. Candidate additions to `ScoringProfile`:

- **Curve / development vs turn count** — board investment relative to turn number
  (ahead/behind the expected curve).
- **Win-condition proximity** — distance to 8 points / to lethal, not just current
  score. A non-linear "closeness" term.
- **Rune/energy development** — runes set up for future turns (partially present as
  `runes_available`, `reactive_potential`).
- **Potential energy / assembled combos** — pieces in play that pay off when
  completed (LLM-identified; see §4).
- **Tempo** — mana/rune efficiency this turn vs board impact gained.
- **Card quality in hand** — not just count; playable threats vs dead cards.

Adding these means the depth-6 leaf at the end of a "setup" turn scores higher, so
the search *chooses* the early-cost play. **This is the highest-value, lowest-risk
fix.**

### 1.3 Fix #2 — outcome-based tuning solves delayed credit automatically
Texel/evolutionary tuning labels every logged position with the **final game
result**, not the immediate reward. So:
- the turn-3 setup position is labeled "win",
- regression/evolution discovers the feature present then (e.g. high
  `reactive_potential`) correlates with winning,
- its weight rises — **rewarding the delayed-payoff move with no manual causal
  tracing.**

This is exactly why **cross-game** tuning matters more than single-game: delayed
causality only emerges in aggregate over hundreds of games. Requires the
`game_outcome` backfill from the storage doc.

### 1.4 Fix #3 (later) — TD/TDLeaf(λ) bootstrapping
TD(λ) propagates value backward along the move sequence; TDLeaf(λ) (KnightCap,
Giraffe) trains the eval at search leaves to predict the next position's leaf
eval — chaining estimates across the horizon without deep search. More powerful
than Texel for mid-game positions. A Phase-2 upgrade after Texel works.

---

## 2. Tuning algorithms — which to use

| Method | Gradient | Cost / update | Best for | Verdict here |
|---|---|---|---|---|
| **Texel** (logistic regression) | approx | many logged positions / pass | many params, outcome-labeled data | **Phase 1: do this first** |
| **SPSA** (Stockfish/fishtest) | stochastic approx | 2 games / step | real-time, high-dim | optional, online tuning |
| **CMA-ES** | none (covariance) | ~10–1000 evals | ~10–300 noisy params | **Phase 2: win-rate refiner** |
| **GA / evolutionary** | none | population × evals | non-differentiable weights | LOCM's choice; CMA-ES subsumes |

References (verified): Texel —
chessprogramming.org/Texel's_Tuning_Method; CMA-ES — Hansen, arXiv:1604.00772;
SPSA — chessprogramming.org/SPSA; LOCM evolved eval — Miernik & Kowalski, ICAART
2022 (evolves a linear weight vector over board features via game-outcome fitness).

### 2.1 Phase 1 — Texel (logistic regression). Fast first pass.
- Dataset: each `search_decisions` row = `chosen_features_json` (vector) +
  `game_outcome` (label). Hundreds of decisions over 50–200+ games.
- Fit: `p = sigmoid(K · Σ w·features)`; minimize MSE/log-loss vs win/loss; solve
  for `w`.
- **Read it two ways:** (a) new weight *values*; (b) **diagnosis** — a fitted
  weight ≈ 0 means the feature does nothing; a **sign flip** (you set +, data says
  −) means it's actively miscalibrated.
- Cheap (one pass over logged data), uses data you already collect. No new games.

**Implementation:** `ai_agent/texel_tune.py` (Phase-1 proposer). Reads
`search_decisions` with the same AND filters as `feature_report.py`, maps each
`chosen_features_json` to the per-weight feature vector (mirroring
`ScoringProfile` term math), and fits standardized logistic weights via
ridge-regularized gradient descent. Outputs a **candidate** `scoring_profile.json`
(`--out`, never overwrites the live profile) plus the two-way diagnosis below.
Terminal positions (`game_over`) are excluded so the `win_game` term can't swamp
the shaping signal; `battlefield_weights`, `end_of_turn`, and `mulligan` are held
fixed in this phase. Run:

```
python ai_agent/texel_tune.py --db ai_agent/selfplay.db --out candidate_profile.json
python ai_agent/texel_tune.py --dry-run --lambda 1.0   # diagnose only
```

Tests: `ai_agent/tests/test_texel_tune.py` (synthetic sign recovery, sign-flip
detection, zero-variance handling, ridge stability on correlated features).

**Caveats specific to this game:**
- **Noisy labels** (shuffle/hidden info) → need many games.
- **Correlated features** (`cards_in_hand`↔`card_drawn`,
  `battlefield_control`↔`battlefields_conquered`) → use **L2/ridge
  regularization** or regression is unstable.
- **The `win_game=1000` term + clamp dominate.** Fit the **shaping features
  separately** from the terminal term, or terminal swamps the signal.

### 2.2 Phase 2 — CMA-ES (win-rate refiner). Robust validator.
- Treat the weight vector as a point; fitness = **self-play win-rate** vs a fixed
  reference profile.
- CMA-ES samples weight vectors from a Gaussian, evaluates by win-rate, moves the
  mean toward winners, and **adapts the covariance matrix** — learning which
  weights correlate and which search directions pay off (handles the correlated
  features Texel struggles with).
- Gradient-free; directly optimizes the thing we care about (win-rate), not a
  proxy. Robust to noise and non-linear feature interactions — why the CCG field
  favors it.
- **Cost: sample-hungry.** Only practical with fast headless **AI-vs-AI + argmax**
  data generation (see storage doc § self-play). This is the dependency.

### 2.3 Recommended pipeline
```
logged data ──Texel──▶ candidate weights ──▶ CMA-ES refine (self-play)
                                              │
                                              ▼
                                   SPRT / win-rate gate vs baseline
                                              │
                                   accept ▶ new weight_version (commit)
                                   reject ▶ discard, log to tuning_runs
```
Texel is the cheap proposer; CMA-ES + self-play is the validator; **only a
win-rate gate (SPRT) commits**. Every accepted change becomes a new
`weight_versions` row; every attempt is recorded in `tuning_runs`.

---

## 3. LLM-proposed hypotheses

The LLM does **not** compute weight values — Texel/CMA-ES beat it at numbers. The
LLM owns the parts that are language/semantics/causality. Verified paradigm:
**LLM-guided search** where the LLM proposes and a simulator validates (OPRO,
arXiv:2309.03409 — demonstrated on weight-vector search; Eureka, arXiv:2310.12931;
FunSearch, Nature 2023; EvoLLM, arXiv:2402.18381).

### 3.1 Post-game causal hypotheses (highest immediate value)
Statistics says "`reactive_potential` correlates with winning." The LLM reads the
logged lines + `score_breakdown` + outcome and says **why**: *"in games 12/19/27
the AI hoarded ready runes for reactions it never used, passing up board
development — the eval over-rewards `reactive_potential`."* Turns a number into a
**trustable diagnosis** and catches **spurious correlations** the regression would
blindly encode.

Inputs: `search_decisions`, `candidate_lines`, `decision_snapshots`, `card_stats`,
`turn_snapshots` (all from the storage doc). Output: ranked hypotheses, each as a
structured proposal (feature, direction, rationale, supporting game ids).

### 3.2 LLM as proposer in the evolutionary loop (OPRO pattern)
Replace blind GA mutation with informed proposals:
```
1. Evaluate candidate weight vectors by self-play win-rate
2. Show LLM the top (weight_vector → win_rate) pairs + breakdown summaries
3. LLM proposes an improved vector WITH a rationale
4. Self-play validates; SPRT gates; feed result back in-context
5. Repeat
```
The LLM brings **game-knowledge priors** ("aggression underperforms vs control —
lower `point_scored` urgency, raise `unit_might_on_board`"); the simulator keeps
it honest. Never commit an LLM number without the win-rate gate.

### 3.3 Failure-mode triage (reasoning, not numbers)
Before tuning weights at all, the LLM classifies each bad decision using the
candidate set:
- **selection error** — best line was in top-N but not chosen (LLM selector slip),
- **search error** — realized-best line never generated (raise beam/depth/budget;
  **no weight change**),
- **eval error** — best line generated but mis-scored (**this** is the tuning
  target).
Routing this correctly prevents tuning weights to fix a search problem.

### 3.4 Opponent prior for the hidden-hand gap
The named blocker ("what will they play next turn") is a hidden-information
judgment, not a search problem. The LLM, given `opponent_actions` history + card
knowledge, estimates a **threat prior** on contested `opponent_windows` the search
already surfaces ("this opponent has shown removal — this window is risky"). Feeds
qualitative judgment the pure search cannot produce.

---

## 4. LLM-designed features

Tuning only adjusts **existing** weights — optimizers can never add a dimension
that isn't in the vector. The LLM can **invent new features**, which is the only
way to close the delayed-value gap of §1.2. This is the Eureka/FunSearch pattern
(LLM writes evaluation *code/terms*, evaluator validates) applied to our
AI-editable `ScoringProfile` schema.

### 4.1 Loop
```
1. LLM reads games the AI lost despite good immediate score_breakdown
2. LLM diagnoses a MISSING concept ("no term rewards developing toward lethal")
3. LLM proposes a new feature: name + how to compute from snapshot/steps + sign
4. Implement the feature extractor in `ScoreModel.build_score_features`
   (`Scripts/Game/ScoreModel.gd`; human-reviewed; this is a code change, gated)
5. Re-tune ALL weights (Texel/CMA-ES) WITH the new feature included
6. Self-play vs baseline; SPRT gate; accept only if win-rate improves
```

### 4.2 Guardrails
- New features are **code**, so step 4 stays human-reviewed (don't autogenerate
  arbitrary GDScript into the engine unchecked).
- A new feature must **earn its place** via the win-rate gate — adding dimensions
  risks overfitting. Prefer few, well-motivated features.
- Watch correlation with existing features (regularize; drop redundant ones).
- Candidate feature backlog from §1.2 (curve/development, win-proximity, tempo,
  potential-energy, hand quality) is the natural first batch.

### 4.3 Why this is the LLM's unique role
| Job | Best tool |
|---|---|
| Find optimal weight *values* | Texel → CMA-ES |
| Explain *why* a weight is wrong | LLM |
| Propose *which* weights/directions to try | LLM (validated by self-play) |
| **Invent *new* features** | **LLM (only option)** |
| Decide eval-vs-search-vs-selection error | LLM |
| Final accept/reject | self-play + SPRT |

Guardrail throughout: **the LLM hypothesizes and explains; the simulator decides.**

---

## 5. Cross-turn planner hook (tying §1 and §3 together)

The branch already has a planner (`ai_agent/planner.py`) that sets a per-turn
intent. Extend it into the cross-turn layer the per-turn search lacks:

- LLM identifies a **multi-turn goal** ("assemble combo X", "race to 8 on
  battlefield-a", "stabilize then win late").
- Planner emits a **temporary scoring bias** for the game/turn — e.g. boost
  `reactive_potential` weight because it spotted a defensive win plan.
- `TurnSearch` executes within the turn under the biased profile.

This gives a clean separation: **LLM plans ACROSS turns (strategy); search
optimizes WITHIN a turn (tactics).** The bias is transient and never overwrites
the tuned base profile — base weights come from §2, the bias is a planner overlay.

---

## 6. Synthesis

| Layer | Handles delayed impact by | Tool | Phase |
|---|---|---|---|
| Eval features | encoding long-term value as leaf-score terms | add to `ScoringProfile` | 1 |
| Weight tuning | labeling positions with final outcome | Texel → CMA-ES | 1→2 |
| Cross-turn planner | LLM sets multi-turn goal → biases eval | extend `planner.py` | 2 |
| Feature invention | LLM proposes new delayed-value terms | Eureka-style + gate | 2→3 |
| Opponent prior | LLM judges hidden-hand threats | `opponent_actions` + LLM | 2 |

**Bottom line:** don't fight the horizon with deeper search. (1) Put delayed value
into the leaf eval as features, (2) let outcome-based tuning assign delayed credit
across games, (3) use the LLM as the cross-turn planner / feature-inventor /
hypothesis-generator that sits ABOVE the per-turn search — the role statistics
cannot fill — always validated by a self-play win-rate gate.

---

## 7. Build order
1. Add delayed-value features to `ScoringProfile` (§1.2) — biggest immediate win.
2. Texel fitter over logged data (§2.1; `ai_agent/texel_tune.py`) — diagnose
   zero/sign-flip weights. **Done.**
3. AI-vs-AI + argmax harness (storage doc) to enable win-rate evaluation.
4. SPRT gate + `weight_versions` / `tuning_runs` (storage doc).
5. CMA-ES refiner (§2.2) over self-play win-rate.
6. LLM post-game hypothesis agent (§3.1) + failure-mode triage (§3.3).
7. LLM feature-invention loop (§4) + cross-turn planner hook (§5).
8. (Later) TDLeaf(λ) (§1.4); LLM-in-the-loop evolution (§3.2).

## 8. References (verified)
- Texel tuning — https://www.chessprogramming.org/Texel%27s_Tuning_Method
- SPSA — https://www.chessprogramming.org/SPSA ; Fishtest — https://tests.stockfishchess.org/
- CMA-ES tutorial — Hansen, https://arxiv.org/abs/1604.00772
- LOCM evolved evaluation functions — Miernik & Kowalski, ICAART 2022; competition
  survey arXiv:2305.11814; repo https://github.com/acatai/Strategy-Card-Game-AI-Competition
- Forge linear eval (reference) — https://github.com/Card-Forge/forge
  (`CreatureEvaluator.java`, `GameStateEvaluator.java`)
- SabberStone linear eval (reference) — https://github.com/HearthSim/SabberStone
  (`AggroScore.cs`)
- OPRO "LLMs as Optimizers" — https://arxiv.org/abs/2309.03409
- Eureka (LLM reward design) — https://arxiv.org/abs/2310.12931
- FunSearch — Nature 2023, https://github.com/google-deepmind/funsearch
- EvoLLM "LLMs as Evolution Strategies" — https://arxiv.org/abs/2402.18381
- TDLeaf(λ) — Baxter, Tridgell & Weaver (KnightCap); Lai (Giraffe), arXiv:1509.01549
