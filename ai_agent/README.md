# Riftbound AI Agent Service

A Python-based OpenAI reasoning agent that plays Riftbound against a human.
Godot sends compact game state JSON; the agent reasons using GPT-4o with
tool-calling skills, then returns a structured decision that Godot validates.

## Quick Start

```bash
# 1. Install dependencies (from workspace root)
pip install -r requirements.txt

# 2. Set your OpenAI API key
export OPENAI_API_KEY=sk-...

# 3. Start the service
uvicorn ai_agent.main:app --port 8765 --reload

# 4. Launch the Riftbound game in Godot
#    The AI player (P2) will connect to localhost:8765 automatically.
#    If the service is unreachable it falls back to the built-in heuristic.
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | (required) | Your OpenAI secret key |
| `RIFTBOUND_AI_MODEL` | `gpt-4o` | OpenAI model to use (e.g. `o1-mini`, `gpt-4o-mini`) |

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/decision` | POST | Main entry — receives BriefState, returns Decision |
| `/health` | GET | Liveness check |
| `/legal_moves` | GET | Current enumerated legal moves (debug) |
| `/state` | GET | Full board state text (debug) |
| `/card/{id}` | GET | Card definition lookup |
| `/rule?q=...` | GET | Rules passage search |
| `/position` | GET | Heuristic position evaluation |

## Architecture

```
Godot (GameController)
  └─ AIPlayer.gd          POST /decision ──► FastAPI (main.py)
       ↑                                          │
       │  command string                     agent.py (loop)
       └─────────────────────────────────────     │
                                            ┌─────┴──────┐
                                       OpenAI API    skills.py
                                                      memory.py (SQLite)
```

## File Structure

```
ai_agent/
  __init__.py       Package marker
  schemas.py        Pydantic models: BriefState, Decision, Move
  system_prompt.py  System instruction (high-freq rules inline)
  memory.py         SQLite episodic event log
  skills.py         Read + helper skill implementations
  agent.py          ~150-line OpenAI reasoning loop
  main.py           FastAPI service
  agent_memory.db   Created at runtime (gitignored)
```

## Decision Schema

Every response from `/decision` has this shape:

```json
{
  "reasoning": "Why this move was chosen",
  "move": {
    "action": "play_card",
    "parameters": {
      "card_id": "noxus-hopeful",
      "destination": "battlefield-a"
    }
  },
  "confidence": "high",
  "alternatives_considered": "Could end turn, but board presence is more valuable."
}
```

Godot's `AIPlayer.gd` translates `move` into a console command string
(`play noxus-hopeful to battlefield-a`) and submits it through the same
`submit_command()` path that a human player uses.

## Memory

Decisions are logged to `ai_agent/agent_memory.db` (SQLite).  Each record stores:
- `game_id`, `turn`, `decision_type`
- `brief_state_hash`, `reasoning`, `move_json`
- `accepted`, `rejection_reason`, `outcome_summary`

The last 10 decisions per game are injected into the agent's context on each
turn to give it continuity within the game.
