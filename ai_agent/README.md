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

| Variable | Default | Required | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | (none) | Yes | Your OpenAI secret key. The service starts without it but every `/decision` call falls back to a safe `pass`. |
| `RIFTBOUND_AI_MODEL` | `gpt-4o` | No | OpenAI model used by both the Planner and Actor stages (e.g. `gpt-4o-mini`, `o1-mini`). |
| `RIFTBOUND_PIPELINE` | `legacy` | No | Decision pipeline mode. `legacy` = single monolithic decision loop. `staged` = Router → Planner → Actor → Validator pipeline. Any other value falls back to `legacy`. |
| `RIFTBOUND_LOG_INPUTS` | `0` | No | When set to a truthy value (anything other than `0`, ``, `false`, `no`), writes debug logs on each decision: full model input to `agent_inputs.log` and the turn plan to `agent_plans.log` (staged pipeline only). |

Notes:
- `RIFTBOUND_LOG_INPUTS` is the single switch for both the input log and the
  plan log. The plan log only produces entries in `staged` mode, since the
  Planner stage does not run under `legacy`.
- The HTTP port is **not** an environment variable. The service is started with
  `uvicorn ... --port 8765`, and the Godot client hardcodes `AGENT_PORT := 8765`
  (`Scripts/AI/AIPlayer.gd`). Change both together if you need a different port.

### Example

```bash
# Staged pipeline with debug logging on a cheaper model
export OPENAI_API_KEY=sk-...
export RIFTBOUND_AI_MODEL=gpt-4o-mini
export RIFTBOUND_PIPELINE=staged
export RIFTBOUND_LOG_INPUTS=1
uvicorn ai_agent.main:app --port 8765 --reload
```

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

## Metrics

python ai_agent/report.py                    # console scorecard
python ai_agent/report.py --json             # raw aggregate JSON
python ai_agent/report.py --charts out/      # + PNG graphs
python ai_agent/report.py --db path/to.db    # custom database