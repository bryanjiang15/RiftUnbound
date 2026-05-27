# Phase 1 — Short-Term Memory Improvements

## Goal

Fix the broken parts of the existing short-term memory system and add opponent
action tracking. No new tables or cross-game learning yet — just making the
within-game context complete and accurate before building on top of it.

---

## What Phase 1 Aims to Fix

### Problem 1: Acceptance tracking is always NULL

Every decision stored in the `decisions` table has `accepted = NULL`. The
`/outcome` endpoint exists in `main.py` but does nothing — it doesn't write the
acceptance status back to SQLite. This means the memory slice shown to the agent
every turn says `→ ?` for every past move instead of `→ OK` or `→ REJECTED`.

The agent cannot learn from its own rejections within a game because the outcomes
are not recorded.

### Problem 2: No opponent action tracking

`get_opponent_history()` in `skills.py` returns only the current-turn public
snapshot (score, hand size, base units). There is no log of what the opponent
has visibly done across prior turns. The agent cannot:
- Detect opponent patterns (aggressive, defensive)
- Track which units the opponent has played
- Identify whether the opponent has been contesting battlefields

### Problem 3: No game outcome ever reaches Python

Godot knows the game result (winner, final scores, turn count) but never sends
it to the Python service. The `/game_over` endpoint does not exist. This blocks
all future phases that depend on knowing whether the game was won or lost.

---

## Changes

### 1. `ai_agent/memory.py`

**Add `opponent_actions` table:**
```sql
CREATE TABLE IF NOT EXISTS opponent_actions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id   TEXT    NOT NULL,
    turn      INTEGER NOT NULL,
    action    TEXT    NOT NULL,
    timestamp TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_opp_game ON opponent_actions (game_id, turn);
```

**New methods:**
- `record_opponent_action(game_id, turn, action)` — append one opponent action
- `opponent_slice(game_id, n=8)` — return last N opponent actions as formatted
  context string (mirrors `recent_slice` for own decisions)

**Add `games` table (minimal, for Phase 2 to build on):**
```sql
CREATE TABLE IF NOT EXISTS games (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id      TEXT UNIQUE NOT NULL,
    outcome      TEXT,          -- 'win' | 'loss' | 'draw' | NULL if in progress
    my_score     INTEGER,
    opp_score    INTEGER,
    turns_played INTEGER,
    timestamp    TEXT NOT NULL
);
```

**New method:**
- `record_game_outcome(game_id, outcome, my_score, opp_score, turns_played)` —
  upsert game result when the game ends

**Fix acceptance tracking:**
- Add `update_acceptance_by_game(game_id, accepted, rejection_reason)` — updates
  the most recent unconfirmed decision for a given game_id. Called from the
  fixed `/outcome` endpoint.

---

### 2. `ai_agent/main.py`

**Fix `/outcome` endpoint:**

Currently:
```python
@app.post("/outcome")
async def outcome_endpoint(body: dict) -> dict:
    logger.info("Outcome: %s", body)
    return {"status": "no-op"}       # ← does nothing
```

After fix, it calls `memory.update_acceptance_by_game(...)` so the `accepted`
and `rejection_reason` columns are actually populated.

**Add `/game_over` endpoint:**
```
POST /game_over
Body: {
  "game_id": str,
  "winner_index": int,
  "my_player_index": int,
  "my_score": int,
  "opp_score": int,
  "total_turns": int
}
Response: { "status": "ok", "outcome": "win"|"loss"|"draw" }
```

Determines win/loss from `winner_index == my_player_index`, writes to the
`games` table. Does NOT trigger the Phase 3 reflection loop yet — just records
the outcome so it is available when Phase 3 is built.

**Add `/opponent_action` endpoint:**
```
POST /opponent_action
Body: {
  "game_id": str,
  "turn": int,
  "action": str    -- human-readable, e.g. "played Iron Shield to base"
}
Response: { "status": "ok" }
```

Calls `memory.record_opponent_action(...)`. Godot calls this whenever an
opponent action becomes visible (card played, unit moved).

---

### 3. `ai_agent/agent.py`

**Inject opponent history into context:**

In `decide()`, after the memory slice injection, add the opponent slice:
```python
opp_slice = memory.opponent_slice(game_id)
if opp_slice:
    messages.append({"role": "user", "content": opp_slice})
```

**Strengthen rejection retry message:**

Currently the rejection context message is:
> "Please choose a different legal move."

After: ask the agent to identify what it misunderstood before replying:
```
## Previous Move Rejected
Rejected move: { ... }
Reason: <rejection_reason>

In one sentence, state what you misunderstood or assumed incorrectly.
Then produce a corrected move.
```

This gives the agent's error identification a chance to appear in `reasoning`,
making the logged decision more useful for future phases.

---

### 4. `Scripts/AI/AIPlayer.gd`

**Call `/outcome` after each move is applied or rejected:**

After `GameController.submit_command()` resolves, check `last_command_error` and
POST to `/outcome`:
```gdscript
func _report_outcome(accepted: bool, rejection_reason: String = "") -> void:
    var body = {
        "game_id": _current_game_id,
        "accepted": accepted,
        "rejection_reason": rejection_reason if not accepted else null
    }
    # fire-and-forget HTTP POST to AGENT_URL.replace("/decision", "/outcome")
```

**Connect to game-over signal and call `/game_over`:**

Connect to `GameController.game_over` signal (or equivalent). On fire:
```gdscript
func _on_game_over(winner_index: int) -> void:
    var gc = _get_controller()
    var body = {
        "game_id": _current_game_id,
        "winner_index": winner_index,
        "my_player_index": player_index,
        "my_score": gc.game_state.players[player_index].score,
        "opp_score": gc.game_state.players[1 - player_index].score,
        "total_turns": gc.game_state.turn_number
    }
    # fire-and-forget POST to /game_over
```

**Log visible opponent actions and POST to `/opponent_action`:**

In the game's `board_updated` callback (already used to trigger AI turns), scan
for newly visible opponent events and forward them:
```gdscript
func _on_opponent_action_visible(turn: int, description: String) -> void:
    var body = {
        "game_id": _current_game_id,
        "turn": turn,
        "action": description    # e.g. "played Iron Shield to base"
    }
    # fire-and-forget POST to /opponent_action
```

---

## What Phase 1 Does NOT Include

- Post-game reflection or lesson extraction (Phase 3)
- Cross-game strategic knowledge or pattern library (Phase 2/3)
- Embedding-based semantic retrieval (Phase 4)
- Claude API migration (Phase 5)
- Any change to the LLM model used

---

## Expected Outcome After Phase 1

1. Memory slice shown to agent each turn displays `→ OK` or `→ REJECTED` instead
   of `→ ?` for every past decision in the current game.

2. Agent context includes an opponent history block:
   ```
   ## Opponent actions (recent, oldest first)
     Turn 2: moved iron-shield to battlefield-a
     Turn 3: played unknown-card to base
     Turn 4: moved iron-shield to battlefield-b
   ```

3. The `games` table records win/loss for every completed game — ready for Phase
   2 stats queries and Phase 3 reflection.

4. The rejection retry prompt is more specific, producing better `reasoning`
   text in the decision log.

---

## Files Changed / Created

| File | Change Type | Summary |
|---|---|---|
| `ai_agent/memory.py` | Modified | `opponent_actions` + `games` tables; new methods for opponent tracking, game outcome, and acceptance update |
| `ai_agent/main.py` | Modified | Fix `/outcome` to write to DB; add `/game_over` and `/opponent_action` endpoints |
| `ai_agent/agent.py` | Modified | Inject `opponent_slice` into context; strengthen rejection retry prompt |
| `Scripts/AI/AIPlayer.gd` | Modified | Call `/outcome` after each move; connect game-over signal; log opponent actions |

No new files are created in Phase 1.
