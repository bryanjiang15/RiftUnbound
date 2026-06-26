# Scoring Features Reference

Status: living reference.

The linear evaluation the search AI uses to rank candidate lines. Features come
from `Scripts/Game/ScoreModel.gd`; weights from `Data/AI/scoring_profile.json`
(applied by `Scripts/Game/ScoringProfile.gd`).

> Scope: these features *drive AI decisions*. They are distinct from the
> descriptive per-card outcome stats in `Card_Statistics_Reference.md`. Don't
> conflate them.

---

## Pipeline

The search AI (`TurnSearch`) scores each candidate line with a **linear weighted
sum**:

```
ScoreModel.snapshot(gs, ai_index)                  # root + leaf snapshots
ScoreModel.build_score_features(root, leaf, steps) # → flat feature dict
ScoringProfile.score_with_breakdown(features)      # → {score, breakdown}
```

Because the eval is linear, `score_breakdown[term] = weight × feature` is an
exact additive per-feature attribution (no SHAP/ablation needed). All weights
live in `Data/AI/scoring_profile.json`; the AI tunes weights only, never invents
terms. Values below are the **current** profile.

## How the final score is assembled (`ScoringProfile.score_with_breakdown`)
1. Compute `win_game` (terminal term, dominating).
2. Compute every other term into `breakdown`.
3. Sum all non-`win_game` terms into `shaping`.
4. **Shaping clamp:** if `|shaping| > win_game - 1`, clamp it to
   `sign(shaping) × (win_game - 1)`. Guarantees no amount of positional shaping
   can ever outweigh an actual win/loss. Sets `shaping_clamped`.
5. `total = win_game + shaping`.

`breakdown` also carries metadata keys: `total`, `points_to_win`
(`victory_score - my_score`), `shaping_clamped`. These are **not** features —
`feature_report.py` excludes them via `_NON_FEATURE_KEYS`.

---

## Terminal term
| Term | Feature(s) | Computation | Weight (`win_game`) |
|---|---|---|---|
| `win_game` | `game_over`, `winner_index`, `ai_index` | `+win_game` if the AI won at the leaf, `-win_game` if it lost, else 0 | **1000.0** |

## State terms (positional: me − opponent at the leaf)
All multiplied by the matching `state_weights` entry.

| Term | Feature | Feature computation (`ScoreModel`) | Weight |
|---|---|---|---|
| `score_diff` | `score_diff` | `my_score − opp_score` | 10.0 |
| `battlefield_control` | `bf` | Σ over battlefields: `+bf_weight` if AI controls, `−bf_weight` if opponent controls, weighted by `battlefield_weights` | 5.0 |
| `unit_might_on_board` | `unit_might_diff` | `my_unit_might − opp_unit_might` (sum of current Might, field + base) | 0.5 |
| `cards_in_hand` | `cards_in_hand_diff` | `my_hand − opp_hand` | 0.3 |
| `runes_available` | `runes_available_diff` | `my_ready_runes − opp_ready_runes` (un-exhausted channeled runes) | −0.1 |
| `reactive_potential` | `reactive_potential` | largest set of Action/Reaction cards in hand simultaneously payable with leftover ready runes (brute-forced over subsets) | 1.0 |
| `unusable_runes` | `unusable_runes` | ready runes no reactive card could ever consume (dead weight): `my_ready_runes − usable_runes` | −0.15 |
| `keywords` | `keyword_net` | per-keyword net presence (mine − opp) dotted with `keyword_weights` | see keyword table |

### Battlefield weights (`battlefield_weights`)
| Battlefield | Weight |
|---|---|
| `battlefield-a` | 1.5 |
| `battlefield-b` | 1.0 |

### Keyword weights (`keyword_weights`)
Net presence = (# my units with the keyword) − (# opp units with it), over the
tracked set `SCORED_KEYWORDS` = assault, shield, tank, ganking, deflect, deathknell.

| Keyword | Weight |
|---|---|
| `assault` | 0.4 |
| `shield` | 0.4 |
| `tank` | 0.6 |
| `ganking` | 0.3 |
| `deflect` | 0.3 |
| `deathknell` | 0.2 |

## Action / outcome terms (root → leaf delta: what the line did)
All multiplied by the matching `action_weights` entry.

| Term | Feature | Feature computation (`ScoreModel`) | Weight |
|---|---|---|---|
| `card_played` | `cards_played` | `my_cards_played` delta (root→leaf) | 1.0 |
| `unit_moved` | `units_moved` | count of scripted `move ` steps in the line | 0.2 |
| `card_discarded` | `cards_discarded` | `my_cards_discarded` delta | −0.5 |
| `enemy_unit_killed` | `enemy_units_killed` | enemy units present at root but gone at leaf | 1.5 |
| `own_unit_lost` | `own_units_lost` | own units present at root but gone at leaf | −1.5 |
| `battlefield_conquered` | `battlefields_conquered` | battlefields newly AI-controlled at leaf **and** scored this turn (re-taking an already-scored bf doesn't count) | 4.0 |
| `point_scored` | `points_scored` | `my_score` delta (root→leaf) | 8.0 |
| `card_drawn` | `cards_drawn` | non-negative `my_hand` increase (root→leaf) | 0.4 |
| `power_used` | `power_used` | non-negative `my_energy` decrease (root→leaf); a small tempo cost | −0.05 |

## End-of-turn term (`end_of_turn`)
A single composite term (`_end_of_turn`):

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

---

## Inspecting features in practice — `ai_agent/feature_report.py`
Reads captured `chosen_breakdown_json` from `search_decisions` and reports, per
feature: in-play %, avg |impact|, active impact, and net direction. Because the
breakdown is exact attribution, these are directly comparable for spotting
mis-weighted terms.

```
python ai_agent/feature_report.py --db ai_agent/selfplay.db --sort impact
```

---

## File map
| Concern | File |
|---|---|
| Scoring features (snapshot + feature math) | `Scripts/Game/ScoreModel.gd` |
| Scoring weights application + clamp | `Scripts/Game/ScoringProfile.gd` |
| Live weights | `Data/AI/scoring_profile.json` |
| Feature impact report CLI | `ai_agent/feature_report.py` |

Related: per-card outcome statistics are documented separately in
`Card_Statistics_Reference.md`.
