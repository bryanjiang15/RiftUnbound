# Card Statistics Reference

Status: living reference.

Descriptive analytics about how each card performs, built from `card_events`
(see `Statistical_Analysis_Storage.md` §3). Read by `ai_agent/card_report.py`.

> Scope: these are **descriptive outcome stats**, distinct from the scoring
> features that *drive* AI decisions (see `Scoring_Features_Reference.md`). Don't
> conflate them.

---

## Source data: `card_events`

One row per card lifecycle event (`memory.py`, table `card_events`). The
aggregation key is the **base `card_def_id`** stamped directly from
`card.definition.id` at emit time — never derived from `instance_id`.

| Column | Meaning |
|---|---|
| `game_id` | match id |
| `turn` | turn number when the event fired |
| `my_player_index` | reporting seat (keeps self-play seats separable) |
| `card_def_id` | base definition id — the aggregation key |
| `instance_id` | per-copy id (e.g. `garen-2`); not used for grouping |
| `event` | one of the lifecycle events below |
| `energy_spent` | energy paid (only meaningful for `played`) |
| `breakdown_delta_json` | optional eval `score_breakdown` contribution |
| `timestamp` | server insert time |

### Lifecycle events (`event` column)
| Event | Emitted when |
|---|---|
| `in_opening_hand` | card dealt in the pre-mulligan opening hand |
| `drawn` | card drawn from deck (draw phase, mulligan redraw) |
| `mulliganed` | card set aside during mulligan |
| `played` | card successfully played (unit/gear/spell/reaction) |
| `discarded` | card discarded from hand |
| `died` | unit destroyed (lethal damage in cleanup) |
| `scored` | reserved (not currently emitted — see note) |
| `left_in_hand_at_end` | card still in hand when the game ended |

> **`scored` note:** the enum reserves `scored`, but scoring in this game is
> battlefield-conquer based, not per-card, so no `scored` event is emitted today.
> The column is kept so the schema is stable if a card-level scoring trigger is
> ever added.

---

## Derived statistics (`memory.card_stats_report` / `card_report.py`)

`games` = total finished games in the DB. `base_win_rate` = won games ÷ games.
Every per-card rate below is computed by aggregating that card's `card_events`.
Cards below `--min-plays` (default 20) are bucketed into a low-sample section.

### Counts (raw)
| Stat | Column / report field | How it's computed |
|---|---|---|
| Games seen | `games_seen` | distinct `game_id` with a `drawn` **or** `in_opening_hand` event |
| Games played | `games_played` | distinct `game_id` with a `played` event |
| Drawn | `drawn` | count of `drawn` events |
| Opening hand | `opening_hand` | count of `in_opening_hand` events |
| Played | `played` | count of `played` events |
| Discarded | `discarded` | count of `discarded` events |
| Deaths | `deaths` / `died` | count of `died` events |
| Stuck | `stuck` | count of `left_in_hand_at_end` events |

### Frequency / tempo (rates)
| Stat | Field | Formula | Reads as |
|---|---|---|---|
| Draw rate | `draw_rate` | `games_seen / games` | how often the card shows up at all |
| Play rate | `play_rate` | `games_played / games` | how often it actually gets played |
| Play-when-drawn | `play_when_drawn_rate` | `played / drawn` | low ⇒ dead/situational card stuck in hand |
| Mulligan rate | `mulligan_rate` | `mulliganed / drawn` | how often the AI throws it back |
| Stuck-in-hand rate | `stuck_in_hand_rate` | `left_in_hand_at_end / drawn` | clogs the hand without being played |
| Avg turn played | `avg_turn_played` | mean `turn` over `played` events | curve position (early vs late) |
| Avg energy | `avg_energy_spent` | mean `energy_spent` over `played` events | realized cost to cast |

> Rates use `drawn` (not `drawn + opening_hand`) as the denominator where noted,
> matching `memory.card_stats_report`. A card only ever in the opening hand and
> never redrawn has `drawn = 0`, so those rates are `null` (shown as `—`).

### Impact
| Stat | Field | Formula | Caveat |
|---|---|---|---|
| Win-rate-when-played | `win_rate_when_played` | games where the **reporting seat** played the card and `games.winner_index == that seat`, ÷ those played games | **survivorship/selection biased**. Do **not** use `games.outcome` (last-writer, wrong for two-seat self-play). |
| Deaths | `deaths` | count of `died` events | raw, not yet a rate |

> **WPA (win-probability added)** is now computed from `turn_snapshots` +
> canonical `games.winner_index` via `ai_agent/analysis/wpa_model.py`.
> `card_associated_wpa` is the mean **own-turn** WPA on turns where the card was
> played minus the mean own-turn WPA baseline, with a game-level bootstrap 95%
> interval and the existing min-play gate. It is **associative, not causal**.
> Multi-card turns list all contributing cards (`multi_card_turn_share`) and do
> **not** split the delta. Event-level card WPA would need future pre/post-action
> snapshots. Rankings are refused below 150 finished games and marked provisional
> below 200. `win_rate_when_played` remains the coarse survivorship-biased signal.

### Caveats baked into the report
1. **Survivorship bias** — `win_rate_when_played` is confounded by the AI
   choosing good spots; treat as coarse signal only.
2. **Sample size** — per-card rates are unstable below ~20 plays; the report
   separates low-sample cards rather than mixing them in.

---

## Running the report — `ai_agent/card_report.py`

```
python ai_agent/card_report.py --db ai_agent/selfplay.db --sort win_rate --desc
```

**Sort keys** (`--sort`, with `--asc` / `--desc` to override default direction):
`played` (default), `seen`, `draw_rate`, `play_rate`, `play_when_drawn`,
`mulligan_rate`, `stuck_rate`, `avg_turn`, `avg_energy`, `deaths`, `win_rate`,
`card_wpa`, `card`.

**Filters:** `--seat 0|1` (reporting seat), `--origin self_play|vs_human|vs_heuristic`
(joined via `search_decisions.game_id`), `--min-plays N` (low-sample threshold).

> **DB path gotcha:** the default is `ai_agent/agent_memory.db`, but the server
> may run with `RIFTBOUND_DB_PATH` pointing elsewhere (e.g. `ai_agent/selfplay.db`
> for self-play). Pass the matching `--db`. The table is created lazily on
> `Memory()` init, so a DB created before this feature won't have `card_events`
> until the server using it restarts.

---

## File map
| Concern | File |
|---|---|
| Card event schema + writes + `card_stats_report` | `ai_agent/memory.py` |
| `/card_event`, `/card_stats` endpoints | `ai_agent/main.py` |
| Card event emission (engine) | `Scripts/Game/GameController.gd`, `Scripts/Game/CleanupProcessor.gd` |
| Card event forwarding (engine→server) | `Scripts/AI/AIPlayer.gd` |
| Per-card report CLI | `ai_agent/card_report.py` |

Related: scoring features are documented separately in
`Scoring_Features_Reference.md`.
