# Riftbound AI Agent — System Design & Memory

Status: baseline design plus current implementation notes. For setup, endpoints,
environment variables, and the freshest runtime architecture, start with
`../README.md`; for search goals and scoring, see `Goal_Oriented_Strategist.md`
and `Scoring_Features_Reference.md`.

## Overview

The Riftbound AI agent is a Python FastAPI service that receives game state from
Godot, reasons over it using an LLM tool loop, and returns a single legal move.

Current runtime options extend the baseline flow below:
- Static prompt text lives in `ai_agent/prompts/*.md` and is assembled by
  `system_prompt.py`; runtime state and schema-specific text stay in code.
- `RIFTBOUND_PIPELINE=staged` routes decisions through
  `router.py` -> `planner.py` -> Actor/Validator in `agent.py`; `legacy` keeps the
  original single Actor loop.
- `RIFTBOUND_SEARCH=on` lets `AIPlayer.gd` run Godot `TurnSearch` and send
  candidate lines to `agent.choose_line`.
- `RIFTBOUND_GOALS=on` adds a pre-search `POST /goals` handshake:
  `strategist.py` emits a `GoalSet`, `goal_compiler.py` builds a transient overlay,
  and `TurnSearch`/`choose_line` rank under that overlay.

```
Godot (GDScript)                     Python (FastAPI — port 8765)
────────────────                     ────────────────────────────
AIPlayer.gd
  take_turn()
    │
    ├── BriefStateSerializer          POST /decision
    │   serialize(game_state)  ──────────────────────────────────►
    │                                  main.py
    └── LegalMoveEnumerator              skill_module.set_state(brief_state)
        (all legal commands)             agent.decide(brief_state, game_id, memory)
                                           │
                                           ├── build_system_prompt()
                                           ├── memory.timeline_slice(game_id)  ← STM
                                           ├── format_brief_state()
                                           └── GPT-4o tool loop (max 6 rounds)
                                                 ├── list_legal_moves
                                                 ├── get_full_state
                                                 ├── get_zone
                                                 ├── get_card_detail
                                                 ├── get_opponent_history
                                                 ├── lookup_rule
                                                 ├── simulate_move
                                                 └── evaluate_position
                                                         │
                                           Decision JSON ◄──────────────────
    submit_command(move.to_command()) ◄──
```

---

## Decision Request / Response

**Request** (`POST /decision`):
```json
{
  "brief_state": { ... BriefState fields ... },
  "game_id": "Player_1-vs-Player_2",
  "rejection_context": null
}
```

**Response** (Decision JSON):
```json
{
  "reasoning": "I have 2 Energy and need board presence...",
  "move": {
    "action": "play_card",
    "parameters": {
      "card_id": "vi-destructive",
      "destination": "base",
      "accelerate": false,
      "target_id": "",
      "from_champion": false,
      "from_hidden": false
    }
  },
  "confidence": "high",
  "alternatives_considered": "Considered moving a unit, but hand pressure is better."
}
```

On rejection (up to 3 retries), the same endpoint is called again with
`rejection_context: { rejected_move, rejection_reason }`. The agent sees the
rejected move and picks a different one.

---

## BriefState — What the Agent Sees

`BriefState` is the complete game snapshot serialized by `BriefStateSerializer.gd`.
Schema version 1.0. Fields visible to the agent:

| Field | Description |
|---|---|
| `game_id`, `turn_number` | Game identity and turn counter |
| `my_player_index`, `turn_player_index` | Seat assignments |
| `current_phase`, `current_state` | Phase (Main, Combat, etc.) and state (Neutral Open, Showdown, etc.) |
| `decision_type` | One of: `mulligan`, `main_phase`, `showdown_focus`, `chain_reaction`, `combat_assignment`, `pending_choice` |
| `my_score`, `opponent_score` | Victory points (win at 8) |
| `my_energy`, `my_power`, `my_runes` | Resources available this turn |
| `my_hand` | Full hand (card names, types, costs, keywords, might) |
| `my_base_units`, `my_champion` | Own units in base and champion zone |
| `opponent_hand_size` | Count only — card contents hidden |
| `opponent_base_units` | Opponent units visible at base |
| `battlefields` | Per-battlefield: controller, my_units, opponent_units, contested flag |
| `legal_moves` | Pre-enumerated list of all legal command strings for this decision |
| `legal_action_categories` | High-level action types available |
| `pending_choice_options` | Options for `pending_choice` decisions (`choose <id>`, `choose yes`/`no`, etc.) |
| `pending_choice_context` | Prompt text, source card, ability description; for discards includes `remaining_discards` |
| `combat_assignment_active`, `remaining_attacker_might`, `damage_assigned` | Combat context |
| `full_state_text` | Human-readable board description from Godot |

---

## Context Injected Into Each Agent Decision

The agent's context window is assembled in this order every turn:

```
1. SYSTEM PROMPT (static, every turn)
   ├── Goal & Role: win by reaching 8 VP, one legal move per decision
   ├── High-Frequency Rules: turn structure, resources, units, battlefields,
   │   combat, keywords (Assault, Shield, Tank, Ganking, Accelerate, etc.)
   └── Output Contract: strict JSON schema, action names + required parameters

2. GAME HISTORY (short-term, per-game)
   └── Last 16 events for this game_id — own decisions and the opponent's
       visible actions merged into one chronologically ordered timeline
       (by timestamp, not two separate per-side logs):
       "Turn 2 [main_phase]: You move_unit(destination=battlefield-a) → OK
        Turn 2: Opponent played unknown-card to base"

3. CURRENT DECISION (fresh every turn)
   ├── Turn / Phase / State / Decision type
   ├── Scores, energy, power, runes
   ├── Hand (full)
   ├── Board (my units, opponent base units, battlefields)
   ├── Legal moves (first 20 shown, rest via tool)
   └── Decision context (pending choices, combat assignment state)

4. REJECTION CONTEXT (only on retry)
   └── "Move X was rejected. Reason: Y. Choose a different legal move."
```

Total context: ~3,000–6,000 tokens per decision.

---

## Short-Term Memory (Current Implementation)

**Storage:** SQLite (`agent_memory.db`), table `decisions`.

**Schema:**
```sql
CREATE TABLE decisions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id          TEXT    NOT NULL,
    turn             INTEGER NOT NULL,
    decision_index   INTEGER NOT NULL,
    decision_type    TEXT    NOT NULL,
    brief_state_hash TEXT    NOT NULL,
    reasoning        TEXT    NOT NULL,
    move_json        TEXT    NOT NULL,
    accepted         INTEGER,          -- NULL=unknown, 1=accepted, 0=rejected
    rejection_reason TEXT,
    outcome_summary  TEXT,
    timestamp        TEXT    NOT NULL
);
```

**Injection:** `memory.timeline_slice(game_id)` merges `decisions` and
`opponent_actions` by `timestamp` (both written with
`datetime.now(timezone.utc).isoformat()` from the same process, so sort order
matches true turn order) into one chronological context block — a single
sequence of "You did X → OK/REJECTED" and "Opponent did Y" lines, not two
separate per-side logs. Each entry is a compact one-liner (action + outcome
only); full reasoning text is written to `agent_decisions.log` for human
review, not injected into the model's context, since it's noise for steering
the next decision rather than something the model needs to re-read.

The on-demand `get_opponent_history` tool mirrors this: it now reads
`memory.opponent_actions_text(game_id)` (set via
`skill_module.set_history_context()` each decision) instead of the old
hard-coded "not yet tracked" placeholder.

**Known gaps:**
- Memory is cleared on server restart (`agent_decisions.log` is truncated).
  SQLite persists across restarts but is never queried cross-game (see
  `Memory_Roadmap.md` Phase 2+).

---

## Long-Term Memory (Not Yet Implemented)

Cross-game knowledge is explicitly marked out of scope in `memory.py:14`:
> *"Cross-game knowledge is intentionally out of scope for now."*

There is no:
- Post-game analysis or reflection
- Persistent strategic lessons
- Card performance statistics
- Opponent pattern tracking
- Any mechanism that causes decisions in game N+1 to benefit from game N

---

## Skills Available to the Agent

| Skill | Type | Description |
|---|---|---|
| `list_legal_moves` | Read | Fresh copy of legal move strings from brief state |
| `get_full_state` | Read | Full board description text from Godot |
| `get_zone(zone_id)` | Read | Focused description of one zone (hand, base, battlefield, runes) |
| `get_card_detail(card_id)` | Read | Full card definition JSON from Data/Cards/ |
| `get_opponent_history` | Read | Opponent public action history from `opponent_actions` plus current public context |
| `lookup_rule(query)` | Read | Keyword search over implementation rules doc |
| `simulate_move(move)` | Helper | Engine-truth result of one move (Phase 2.5): structured facts from Godot's rules engine run on a clone, not a heuristic guess |
| `simulate_line(moves[])` | Helper | Engine-truth result of a scripted multi-step line of the AI's own moves (e.g. enter combat then play a trick) |
| `evaluate_position` | Helper | Heuristic assessment: score gap, unit counts, BF control |

---

## Heuristic Fallback

If the API call fails or the agent exhausts all 6 tool rounds without a valid
decision, `AIPlayer.gd` falls back to a deterministic heuristic:

- **Mulligan:** always keep
- **Pending choice:** pick first option
- **Showdown / Chain:** pass
- **Combat assignment:** assign all damage to first unit
- **Main phase:** play highest-cost playable card → move ready units toward
  objectives → end turn

---

## File Map

| File | Purpose |
|---|---|
| `ai_agent/main.py` | FastAPI app, `/decision`, `/goals`, `/health`, feedback/metrics endpoints, lifespan setup |
| `ai_agent/agent.py` | Legacy Actor loop, staged Actor/Validator, search line selector, goal overlay orchestration |
| `ai_agent/router.py` | Staged-pipeline routing: forced commands, prompt modules, plan requirement |
| `ai_agent/planner.py` | Cached per-turn plan for staged decisions |
| `ai_agent/strategist.py` | Cached per-turn `GoalSet` producer for goal-oriented search |
| `ai_agent/goal_compiler.py` | Whitelisted `GoalSet` -> transient scoring-profile overlay |
| `ai_agent/schemas.py` | Pydantic models: BriefState, Move, Decision, GoalSet, CandidateLine, requests |
| `ai_agent/skills.py` | Read/helper skills, including search-scout context for the Strategist |
| `ai_agent/memory.py` | SQLite episodic log, tuning dataset tables, card events, reports |
| `ai_agent/capture.py` | Shared live/offline capture writes for tuning data |
| `ai_agent/prompts/*.md` | Static prompt modules loaded by `ai_agent/prompts/__init__.py` |
| `ai_agent/system_prompt.py` | Prompt assembly, conditional modules, visible-keyword block, goal vocabulary |
| `ai_agent/format_decisions.py` | CLI viewer for `agent_decisions.log` with ANSI color |
| `Scripts/AI/AIPlayer.gd` | Godot HTTP bridge: serializes state, POSTs, retries, fallback |
| `Scripts/AI/BriefStateSerializer.gd` | GameState → BriefState JSON (schema v1.0) |
| `Scripts/AI/LegalMoveEnumerator.gd` | Enumerates all legal command strings per decision type |
