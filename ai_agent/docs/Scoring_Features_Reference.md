# Scoring Features Reference

Status: living reference.

The linear evaluation the search AI uses to rank candidate lines. Feature **specs**
live in `Scripts/Game/FeatureRegistry.gd` (single source of truth); raw feature
**values** are computed in `Scripts/Game/ScoreModel.gd`; weights come from
`Data/AI/scoring_profile.json` (applied by `Scripts/Game/ScoringProfile.gd`).

> Scope: these features *drive AI decisions*. They are distinct from the
> descriptive per-card outcome stats in `Card_Statistics_Reference.md`. Don't
> conflate them.

This game is a **per-battlefield, objective-control point race to 8** (see
`docs/Game Rules/riftbound-implementation-rules.md` §10–13), not a life-total
race. The feature set is built around that: per-battlefield Might, win-proximity,
recurring Hold income, tempo (exhaustion), and contestation/fragility.

---

## Pipeline

The search AI (`TurnSearch`) scores each candidate line with a **linear weighted
sum** driven by the feature registry:

```
ScoreModel.snapshot(gs, ai_index)                  # root + leaf snapshots
ScoreModel.build_score_features(root, leaf, steps) # → flat raw-feature dict
ScoringProfile.score_with_breakdown(features)      # iterate FeatureRegistry.specs()
                                                   #   → {score, breakdown}
```

Because the eval is linear, `score_breakdown[term] = weight × feature` is an
exact additive per-feature attribution (no SHAP/ablation needed). The AI tunes
weights only, never invents terms (except via the gated feature-invention loop,
see §Situational). Values below are the **current** profile (schema 3.0).

## The feature registry (single source of truth)

Every scored feature is described **once** as a declarative spec in
`FeatureRegistry.specs()`:

```
{ id, group, kind, feature_key, weight_key?, subweights?, sign_hint, doc }
```

- `group` → which weights block applies: `state` → `state_weights`,
  `action` → `action_weights`, `situational` → `situational_weights`.
- `kind`:
  - `scalar` → `term = features[feature_key] × weight(group, weight_key)`
  - `dict_weighted` → `term = (Σ features[feature_key][k] × subweights[k])`,
    optionally × the group weight named by `weight_key`.
    Battlefield terms (`battlefield_control`, `battlefield_might_margin`) carry a
    group `weight_key`; `keywords` uses its sub-weights only.

`ScoringProfile.score_with_breakdown` is a **generic loop** over the specs; only
`win_game` (terminal) and `end_of_turn` (composite) are special-cased.

**To add or change a scored feature you touch two places:** compute its raw value
in `ScoreModel.build_score_features`, and add/edit its spec in `FeatureRegistry`
(plus a default weight in `scoring_profile.json`). Then regenerate the manifest:

```
<godot> --headless --script res://Scripts/Tools/ExportFeatureRegistry.gd
```

This writes `Data/AI/feature_registry.json`, the manifest the Python tooling
(`texel_tune.py`, `feature_report.py`) loads so it can **never drift** from the
GDScript scorer.

## How the final score is assembled (`ScoringProfile.score_with_breakdown`)
1. Compute `win_game` (terminal term, dominating).
2. Loop the registry: `breakdown[spec.id] = term(features, spec)`.
3. Compute `end_of_turn` (composite).
4. Sum all non-`win_game` terms into `shaping`.
5. **Shaping clamp:** if `|shaping| > win_game − 1`, clamp to
   `sign(shaping) × (win_game − 1)`. No amount of positional shaping can outweigh
   an actual win/loss. Sets `shaping_clamped`.
6. `total = win_game + shaping`.

`breakdown` also carries metadata keys: `total`, `points_to_win`
(`victory_score − my_score`), `shaping_clamped`. These are **not** features —
`feature_report.py` excludes them via `_NON_FEATURE_KEYS`.

---

## Terminal term
| Term | Computation | Weight (`win_game`) |
|---|---|---|
| `win_game` | `+win_game` if the AI won at the leaf, `−win_game` if it lost, else 0 | **1000.0** |

## State terms (positional; leaf snapshot)

### Win condition & race
| Term | Feature computation (`ScoreModel`) | Weight |
|---|---|---|
| `score_diff` | `my_score − opp_score` | 10.0 |
| `win_proximity` | convex closeness: `(my/victory)² − (opp/victory)²` | 12.0 |
| `hold_income` | battlefields I control **not yet scored this turn** (future Hold points) | 3.0 |

`win_proximity` is the one nonlinearity, and it lives in the *feature* (not the
weight), so the weight layer stays linear and per-term attribution stays exact.

### Battlefield control & contestation (the positional core)
| Term | Feature computation | Weight |
|---|---|---|
| `battlefield_control` | `dict_weighted` over `bf_control_net` (+1 mine / −1 opp / 0), × `battlefield_weights`, × `battlefield_control` | 5.0 |
| `battlefield_might_margin` | `dict_weighted` over per-bf `(my − opp) Might`, × `battlefield_weights`, × `battlefield_might_margin` | 0.4 |
| `control_fragility` | my threats on opp battlefields − opp threats on mine, where a "threat" is enough ready mobile Might (reserve at Base) to overcome the holder's Might | 1.5 |

`battlefield_might_margin` replaces the old **global** `unit_might_diff` as the
primary board-strength signal: 10 Might at one battlefield no longer counts toward
another. This is the single biggest correctness fix for this game.

### Development & tempo
| Term | Feature computation | Weight |
|---|---|---|
| `unit_might_on_board` | global `(my − opp) Might` (field + base); weak fallback | 0.15 |
| `ready_unit_might` | `(my − opp)` Might of **un-exhausted** units deployed to battlefields | 0.3 |
| `idle_base_might` | `(my − opp)` Might sitting at Base, off-objective | −0.1 |
| `damage_fragility` | `Σ enemy damage/Might − Σ my damage/Might` (progress toward death) | 1.0 |
| `keywords` | `dict_weighted` over per-keyword net presence (mine − opp), × `keyword_weights` | see table |

### Card & resource advantage
| Term | Feature computation | Weight |
|---|---|---|
| `cards_in_hand` | `my_hand − 0.8 × opp_hand` (asymmetric; own cards worth more, per Forge) | 0.3 |
| `rune_development` | `(my − opp)` channeled runes (persistent ramp) | 0.3 |
| `reactive_potential` | largest set of Action/Reaction cards in hand simultaneously payable with leftover ready runes | 1.0 |
| `unusable_runes` | ready runes no reactive card could ever consume (dead weight) | −0.15 |

### Battlefield weights (`battlefield_weights`)
| Battlefield | Weight |
|---|---|
| `battlefield-a` | 1.5 |
| `battlefield-b` | 1.0 |

### Keyword weights (`keyword_weights`)
Net presence = (# my units with the keyword) − (# opp units with it), over
`SCORED_KEYWORDS` = assault, shield, tank, ganking, deflect, deathknell.

| Keyword | Weight |
|---|---|
| `assault` | 0.4 |
| `shield` | 0.4 |
| `tank` | 0.6 |
| `ganking` | 0.3 |
| `deflect` | 0.3 |
| `deathknell` | 0.2 |

> Note: keyword presence is currently counted flat. Scaling combat keywords
> (assault/shield) by the unit's Might is a candidate refinement, deferred to the
> tuning/feature-invention loop.

## Action / outcome terms (root → leaf delta: what the line did)
| Term | Feature computation | Weight |
|---|---|---|
| `card_played` | `my_cards_played` delta | 1.0 |
| `unit_moved` | count of scripted `move ` steps in the line | 0.2 |
| `card_discarded` | `my_cards_discarded` delta | −0.5 |
| `enemy_unit_killed` | enemy units present at root but gone at leaf | 1.5 |
| `own_unit_lost` | own units present at root but gone at leaf | −1.5 |
| `battlefield_conquered` | battlefields newly AI-controlled **and** scored this turn | 4.0 |
| `point_scored` | `my_score` delta | 8.0 |
| `card_drawn` | non-negative `my_hand` increase | 0.4 |
| `power_used` | non-negative `my_energy` decrease (small tempo cost) | −0.05 |

## End-of-turn term (`end_of_turn`)
A single composite term:

```
end_of_turn = -|my_hand - hand_size_target| * hand_size_weight
              + my_ready_runes * rune_weight
```

| Param | Value | Meaning |
|---|---|---|
| `hand_size_target` | 3 | preferred end-of-turn hand size |
| `hand_size_weight` | 0.3 | penalty per card away from target |
| `rune_weight` | 0.2 | reward per leftover ready rune |

## Mulligan sub-profile (`mulligan`)
Separate from line scoring; governs the mulligan keep/throw decision (not part of
`build_score_features`). Documented here for completeness.

| Param | Value | Meaning |
|---|---|---|
| `max_set_aside` | 2 | max cards mulliganed |
| `keep_threshold` | 3.0 | min card value to keep |
| `cost_prior` | {0:3, 1:4, 2:7, 3:5, 4:2, 5:1, default:0.5} | value prior by energy cost (curve preference) |
| `low_cost_unit_prior` | 10.0 | bonus for cheap units (early board) |
| `low_cost_unit_max_cost` | 2 | "cheap" threshold for the above |

> Weight values above are reasonable priors, not tuned optima. Real values come
> from Texel → CMA-ES behind the self-play win-rate (SPRT) gate — see
> `Score_Tuning_And_Evolution.md`.

---

## Situational / specialized features (scaffold)

A **situational** feature group lets the future LLM feature-invention loop add
specific, conditional terms — e.g. "combo A+B assembled", "played card X on turn
1" — **without engine code changes**. Specs are loaded from
`Data/AI/situational_features.json` (`{ id, predicate, value, weight }`, a
restricted safe expression over snapshot fields, *not* raw GDScript) and folded
into the manifest by the exporter. The group is currently **empty** (scaffold
only); `situational_weights` in the profile is `{}`.

Do not confuse this static scaffold with the **runtime goal overlay** from
`goal_compiler.py`. `RIFTBOUND_GOALS` can attach per-turn `situational_terms` and
`card_bonuses` to candidate-line re-ranking without editing
`Data/AI/situational_features.json` or the base scoring profile. Those terms are
transient strategy bias, not durable learned features; if a concept proves useful
across games, promote it through the registry/scaffold workflow above and validate
it with tuning/self-play.

### Why situational features (research summary)
In linear-ML terms these are **feature crosses / conditional indicators**: sparse
binary (or small-integer) features that fire only in specific states. A linear
model *cannot* learn an AND/combo from atomic features — the cross term must be
constructed explicitly. So combo/situational features are exactly how you inject
nonlinear, card-specific knowledge into an otherwise linear eval.

**They are good additions, with guardrails.** Reference evals agree (Forge pushes
specificity into a per-card value table + per-keyword scaling — specificity as
*data*, not bespoke branches; LOCM winners keep a compact linear eval and add
specialized knowledge sparingly). Tradeoffs to respect:

- **Combinatorial explosion** — one feature per card-pair is unbounded. Prefer
  *parameterized* terms ("combo-proximity = fraction of a named combo assembled",
  "on-curve development vs turn N") over hardcoded ("card#47 + card#12").
- **Overfitting** — sparse features fire rarely, so their weights are estimated
  from little data. Keep them few; regularize; prune dead ones with
  `feature_report.py`.
- **Maintenance** — config-driven specs, never hardcoded `if card_id == …`.

**Design verdict:** treat situational features as a separate, additive namespace
(`situational_weights`) layered on the core differential eval, each term a
declarative spec. Every term must **earn its place via the SPRT win-rate gate**
(Score_Tuning_And_Evolution.md §4): the LLM proposes a spec, a human reviews the
predicate, the simulator decides.

---

## Inspecting features in practice — `ai_agent/feature_report.py`
Reads captured `chosen_breakdown_json` from `search_decisions` and reports, per
feature: in-play %, avg |impact|, active impact, and net direction. It discovers
terms directly from the breakdown keys, so new registry features appear
automatically — no code change needed.

```
python ai_agent/feature_report.py --db ai_agent/selfplay.db --sort impact
```

## Tuning weights from outcomes — `ai_agent/texel_tune.py`
Texel's method (logistic regression): fits the weights above so that
`sigmoid(K · eval)` predicts each logged position's final `game_outcome`. The
weight↔feature mapping is **derived from `feature_registry.json`** (the exported
manifest), so adding a feature in GDScript + regenerating the manifest makes Texel
regress it automatically. Reads `chosen_features_json` + `game_outcome`, excludes
terminal positions, ridge-regularizes, and writes a **candidate** profile plus a
sign-flip / dead-weight diagnosis. Proposer only — validate via self-play
win-rate before committing. See `Score_Tuning_And_Evolution.md` §2.1.

```
python ai_agent/texel_tune.py --db ai_agent/selfplay.db --out candidate_profile.json
```

> Removing/renaming a feature changes the feature vector. Bump `weight_version`
> when doing so; old logged rows tune under their own version, and the Python
> mirror reads missing keys as 0 so it stays robust to schema drift.

---

## File map
| Concern | File |
|---|---|
| Feature specs (single source of truth) | `Scripts/Game/FeatureRegistry.gd` |
| Raw feature math (snapshot + flatten) | `Scripts/Game/ScoreModel.gd` |
| Generic weighted-sum + clamp | `Scripts/Game/ScoringProfile.gd` |
| Live weights | `Data/AI/scoring_profile.json` |
| Exported manifest (Python consumes) | `Data/AI/feature_registry.json` |
| Situational spec config (scaffold) | `Data/AI/situational_features.json` |
| Manifest exporter | `Scripts/Tools/ExportFeatureRegistry.gd` |
| Feature impact report CLI | `ai_agent/feature_report.py` |
| Texel weight tuner (proposes new weights) | `ai_agent/texel_tune.py` |
| Feature unit tests | `Scripts/Tests/Tcg/suites/RuleScoreFeaturesTests.gd` |

Related: per-card outcome statistics are documented separately in
`Card_Statistics_Reference.md`.
