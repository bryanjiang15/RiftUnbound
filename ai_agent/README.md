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
| `RIFTBOUND_LOG_INPUTS` | `0` | No | When set to a truthy value (anything other than `0`, ``, `false`, `no`), writes debug logs on each decision: full model input to `agent_inputs.log`, the turn plan to `agent_plans.log` (staged pipeline only), the per-decision tool-call trace + outcome to `agent_tools.log`, and post-event game snapshots to `agent_game_state.log`. |
| `RIFTBOUND_CLIENT_MAX_RETRIES` | `2` | No | How many times the OpenAI SDK itself retries a failed request (with its own backoff that respects `Retry-After`). |
| `RIFTBOUND_TRANSIENT_RETRIES` | `3` | No | Extra in-process retries layered on top of the SDK for transient failures (rate limits / 429, timeouts, connection drops, 5xx) before a decision degrades to a fallback `pass`. |
| `RIFTBOUND_TRANSIENT_BACKOFF_S` | `1.0` | No | Base seconds for exponential backoff between in-process transient retries (used when the error carries no `Retry-After` header). |
| `RIFTBOUND_SEARCH` | `off` | No | Enables engine search mode. When on, Godot runs `TurnSearch` and posts candidate lines; the server selects a line (via `choose_line`) and captures the tuning dataset (`search_decisions` / `candidate_lines` / `decision_snapshots`). |
| `RIFTBOUND_SEARCH_ARGMAX` | `off` | No | When on (with search enabled), skips the LLM line-selector round-trip and returns the top-scored line directly. Decisions are tagged `selector_source='argmax'`. Use for bulk data generation / weight tuning. |
| `RIFTBOUND_DATA_ORIGIN` | `vs_human` | No | Provenance tag stamped on captured `search_decisions` rows: `vs_human`, `self_play`, or `vs_heuristic`. Keeps state distributions separable so they are never silently mixed in tuning. |
| `RIFTBOUND_CAPTURE_SEAT` | (unset) | No | When `0` or `1`, persist the tuning dataset (`search_decisions` / `candidate_lines` / `decision_snapshots`) for **only that seat's** decisions. Use in two-profile self-play to store data from just the profile under test (put it on this seat). Unset/invalid = capture both seats. |
| `RIFTBOUND_DB_PATH` | (default `ai_agent/agent_memory.db`) | No | Override the SQLite database path. Useful to write self-play data to a dedicated file (e.g. `ai_agent/selfplay.db`) instead of the live-play DB. |


Notes:
- `RIFTBOUND_LOG_INPUTS` is the single switch for the input log, the plan log,
  the tool log, and the game state log. The plan and tool logs only produce
  entries in `staged` mode, since the Planner/Actor stages do not run under
  `legacy`.
- `agent_game_state.log` records post-move state after meaningful accepted AI
  decisions (non-forced and not `pass` / `end turn`), state snapshots at chain
  and combat resolution points, and one-line opponent actions without state.
- `agent_tools.log` records, per decision, every tool the model called (round,
  name, args) and the terminal `Outcome` — the chosen action, or the exact reason
  it fell back to `pass` (validator budget exhausted, transient API failure after
  retries, etc.). Use it to tell rate-limit fallbacks apart from validator
  rejections.
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

### Token usage

Each decision records OpenAI token usage (`prompt`, `completion`, `total`),
split between the two agents so their cost can be compared independently:

- **planner agent** — produces the per-turn strategic plan (staged pipeline;
  usually cached once per turn).
- **decision agent** (actor) — selects the concrete legal move each decision.

Per-decision rows live in `decision_eval_metrics` (overall + `planner_*` /
`actor_*` token + call columns); per-game totals roll up into
`game_eval_summary`. The scorecard's "Token Usage (planner vs decision agent)"
section and the `server_side.tokens` block of `--json` surface the breakdown.
Rows recorded before this feature show zero tokens.

## Tuning dataset (search mode)

When `RIFTBOUND_SEARCH` is on, every engine-searched decision is captured for
later score tuning (see `docs/Statistical_Analysis_Storage.md`):

- `weight_versions` — the active `Data/AI/scoring_profile.json`, hashed + tagged
  with the current git SHA, recorded on server start.
- `search_decisions` — one row per searched decision: chosen/best score, regret,
  score margin, the chosen line's raw feature vector (`chosen_features_json`) and
  `score_breakdown`, search stats, `selector_source` (`llm` | `fallback` |
  `argmax`), `origin`, and the deciding seat (`my_player_index`).
- `candidate_lines` — every candidate per decision (rank, score, moves, features,
  breakdown) for search-vs-eval-vs-selection error analysis.
- `decision_snapshots` — full `BriefState` + extracted scalar columns.
- Backfilled on `/game_over`: `game_outcome`, `final_score_diff`, and
  `went_first` (seat-aware, so two-seat self-play under one `game_id` is not
  cross-contaminated). `games` also stores `first_player_index` and `seed`.

### Self-play data generation

`Scripts/Tools/SelfPlaySim.gd` runs headless AI-vs-AI games where both seats use
the argmax short-circuit (no LLM), generating bulk tuning data fast.

```bash
# 1. Start the agent server in argmax self-play mode on a dedicated DB.
RIFTBOUND_SEARCH=on RIFTBOUND_SEARCH_ARGMAX=on \
RIFTBOUND_DATA_ORIGIN=self_play RIFTBOUND_DB_PATH=ai_agent/selfplay.db \
  uvicorn ai_agent.main:app --port 8766

# 2. Run N games against it (Godot headless).
#    RIFTBOUND_AGENT_PORT points the engine at the server above;
#    RIFTBOUND_AI_THINK_DELAY=0 removes the per-move readability delay.
RIFTBOUND_SEARCH=on RIFTBOUND_AGENT_PORT=8766 RIFTBOUND_AI_THINK_DELAY=0 \
  <godot> --headless --path . --script res://Scripts/Tools/SelfPlaySim.gd -- \
    --games 50 --seed 1000 --turn-cap 200
```

#### Offline capture (no server) — faster bulk runs

In argmax self-play the server does **no LLM work**: it only picks the
highest-scoring searched line (a pure function of scores the engine already
computed) and writes SQL. The per-decision HTTP round-trip is therefore pure
overhead. Set `RIFTBOUND_SELFPLAY_CAPTURE` to a log path and the engine computes
the argmax decision locally and appends every server-bound payload to a JSONL
file — **no server needs to be running**. After the run, replay the log into
SQLite with `ai_agent/import_selfplay_logs.py`, which writes identical rows via
the same `ai_agent/capture.py` helpers the live `/decision` endpoint uses.

```bash
# 1. Run N games with NO server. RIFTBOUND_SELFPLAY_CAPTURE points at the log
#    (use "1" for the default res://out/selfplay_capture.jsonl). Search mode is
#    forced on; the /health handshake is skipped.
RIFTBOUND_SELFPLAY_CAPTURE=res://out/selfplay_capture.jsonl RIFTBOUND_AI_THINK_DELAY=0 \
  <godot> --headless --path . --script res://Scripts/Tools/SelfPlaySim.gd -- \
    --games 50 --seed 1000 --turn-cap 200

# 2. Import the captured log into the tuning DB (origin defaults to self_play).
python -m ai_agent.import_selfplay_logs out/selfplay_capture.jsonl \
    --db ai_agent/selfplay.db --origin self_play [--capture-seat 0]
```

The importer reproduces the server's selection with the same `_argmax_line`, and
parity-checks the engine's recorded choice against it (warns on any mismatch).
`--p1-profile` / `--p2-profile` and `RIFTBOUND_CAPTURE_SEAT` behave exactly as in
the live path. This removes **all** per-decision HTTP (≈the entire server-comms
cost of a run); the wall-clock becomes dominated by `TurnSearch` itself.

#### A/B-testing two scoring profiles

Pass `--p1-profile` / `--p2-profile` to give each seat its own scoring-profile
JSON (omit a flag to use the live default `Data/AI/scoring_profile.json`). This
pits a tuned candidate (e.g. from `ai_agent/texel_tune.py`) against the baseline;
the per-seat win-rate is the gate that decides whether to commit the candidate.
Each `TurnSearch` scores under its seat's profile, and argmax selection uses those
engine-computed scores, so the two seats genuinely play different weights.

```bash
RIFTBOUND_SEARCH=on RIFTBOUND_AGENT_PORT=8766 RIFTBOUND_AI_THINK_DELAY=0 \
  <godot> --headless --path . --script res://Scripts/Tools/SelfPlaySim.gd -- \
    --games 50 --seed 1000 \
    --p1-profile res://Data/AI/candidate_profile.json \
    --p2-profile res://Data/AI/scoring_profile.json
```

Paths may be `res://…` or absolute OS paths. Alternate which seat gets the
candidate across runs (or randomise `--seed`/first player) to cancel
first-player advantage.

#### Storing data from only one profile

Both seats POST to the same server, so by default **both** seats' decisions are
captured (tell them apart via the `my_player_index` column, or
`feature_report.py --seat` / `texel_tune.py --seat`). To store **only** the
profile-under-test, set `RIFTBOUND_CAPTURE_SEAT` to that seat on the server and
put the test profile on the matching seat:

```bash
# Server: capture ONLY seat 0's decisions.
RIFTBOUND_SEARCH=on RIFTBOUND_SEARCH_ARGMAX=on \
RIFTBOUND_DATA_ORIGIN=self_play RIFTBOUND_DB_PATH=ai_agent/selfplay.db \
RIFTBOUND_CAPTURE_SEAT=0 \
  uvicorn ai_agent.main:app --port 8766

# Engine: seat 0 = candidate (captured), seat 1 = baseline (not captured).
RIFTBOUND_SEARCH=on RIFTBOUND_AGENT_PORT=8766 RIFTBOUND_AI_THINK_DELAY=0 \
  <godot> --headless --path . --script res://Scripts/Tools/SelfPlaySim.gd -- \
    --games 50 --seed 1000 \
    --p1-profile res://Data/AI/candidate_profile.json \
    --p2-profile res://Data/AI/scoring_profile.json
```

The unkept seat still plays (providing a real opponent) but writes no tuning
rows, and `/game_over` backfill is seat-scoped so the kept seat's labels stay
correct.

> **Per-seat weight-version attribution:** the engine sends each seat's actual
> scoring profile with every search decision, so a captured row's
> `weight_version_id` reflects the **exact weights that produced it** — even when
> the two seats run different `--pN-profile` files. Each distinct profile is
> registered as its own `weight_versions` row on first sight. (Live play / older
> engines that send no profile fall back to the one the server read at startup
> from `Data/AI/scoring_profile.json`.) So you can train on just the profile under
> test with `texel_tune.py --weight-version <id>` — look the id up via the
> `weight_versions` table (optionally by a `profile_id` field embedded in the
> profile JSON).

Engine-side env vars consumed by `Scripts/AI/AIPlayer.gd`:

| Variable | Default | Description |
|---|---|---|
| `RIFTBOUND_AGENT_PORT` | `8765` | Agent server port the engine connects to. |
| `RIFTBOUND_AI_THINK_DELAY` | `0.5` | Per-decision delay (seconds); set `0` for bulk runs. |
| `RIFTBOUND_SEARCH` | `off` | Pre-handshake search default (the server's `/health` is authoritative). |
| `RIFTBOUND_SELFPLAY_CAPTURE` | (unset) | When set (a log path, or `1`/`on` for the default `res://out/selfplay_capture.jsonl`), run fully offline: compute argmax locally, skip the server, and append every server-bound payload to the JSONL log for `import_selfplay_logs.py`. Forces search mode on. |