# Riftbound AI Agent Service

A Python-based OpenAI-compatible reasoning agent that plays Riftbound against a
human. Godot sends compact game state JSON; the agent reasons with configured
LLM models and tool-calling skills, then returns structured decisions or
engine-verified line commitments that Godot validates.

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
| `RIFTBOUND_LLM_PROVIDER` | `openai` | No | Which LLM backend to use. `openai` = OpenAI API (uses `OPENAI_API_KEY`). `azure` = Azure AI Foundry's OpenAI-compatible endpoint (uses `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY`). Under `azure`, the model names (`RIFTBOUND_AI_MODEL`, `RIFTBOUND_STRATEGIST_MODEL`) are treated as Azure **deployment** names. |
| `OPENAI_API_KEY` | (none) | Yes* | Your OpenAI secret key (required when `RIFTBOUND_LLM_PROVIDER=openai`). The service starts without it but every `/decision` call falls back to a safe `pass`. |
| `AZURE_OPENAI_ENDPOINT` | (none) | Yes* | Your Azure AI Foundry endpoint. Either the full v1 base URL (`https://<resource>.services.ai.azure.com/openai/v1`) or the bare resource URL (`https://<resource>.services.ai.azure.com`) — the service appends `/openai/v1` if missing. Required when `RIFTBOUND_LLM_PROVIDER=azure`. |
| `AZURE_OPENAI_API_KEY` | (none) | Yes* | Your Azure OpenAI API key. Required when `RIFTBOUND_LLM_PROVIDER=azure`. |
| `RIFTBOUND_AI_MODEL` | `gpt-4o` | No | OpenAI model used by the Planner and Actor stages (e.g. `gpt-4o-mini`, `o1-mini`). |
| `RIFTBOUND_STRATEGIST_MODEL` | (falls back to `RIFTBOUND_AI_MODEL`) | No | OpenAI model for the per-turn goal Strategist ONLY (`RIFTBOUND_GOALS=on`). Planning benefits most from a stronger/reasoning model, and the Strategist runs at most once per turn (cached), so its cost is amortized — point it at a bigger model here without changing the cheaper Planner/Actor. Unset ⇒ uses `RIFTBOUND_AI_MODEL`. Reasoning models (o-series, `gpt-5`) are auto-detected so `temperature` is dropped. The Strategist always runs the think/format split: it first deliberates freely in prose (with tools), then a second call serializes that reasoning into the strict `GoalSet` JSON. |
| `RIFTBOUND_PIPELINE` | `legacy` | No | Decision pipeline mode. `legacy` = single monolithic decision loop. `staged` = Router → Planner → Actor → Validator pipeline. Any other value falls back to `legacy`. |
| `RIFTBOUND_LOG_INPUTS` | `0` | No | When set to a truthy value (anything other than `0`, ``, `false`, `no`), writes debug logs on each decision: full model input to `agent_inputs.log`, the turn plan to `agent_plans.log` (staged pipeline only), the per-decision tool-call trace + outcome to `agent_tools.log`, post-event game snapshots to `agent_game_state.log`, and searched candidate lines / goal overlays to `agent_search.log` when search mode is on. |
| `RIFTBOUND_CLIENT_MAX_RETRIES` | `2` | No | How many times the OpenAI SDK itself retries a failed request (with its own backoff that respects `Retry-After`). |
| `RIFTBOUND_TRANSIENT_RETRIES` | `3` | No | Extra in-process retries layered on top of the SDK for transient failures (rate limits / 429, timeouts, connection drops, 5xx) before a decision degrades to a fallback `pass`. |
| `RIFTBOUND_TRANSIENT_BACKOFF_S` | `1.0` | No | Base seconds for exponential backoff between in-process transient retries (used when the error carries no `Retry-After` header). |
| `RIFTBOUND_SEARCH` | `off` | No | Enables engine search mode. When on, Godot runs `TurnSearch` and posts candidate lines; the server selects a line (via `choose_line`) and captures the tuning dataset (`search_decisions` / `candidate_lines` / `decision_snapshots`). |
| `RIFTBOUND_SEARCH_ARGMAX` | `off` | No | When on (with search enabled), skips the LLM line-selector round-trip and returns the top-scored line directly. Decisions are tagged `selector_source='argmax'`. Use for bulk data generation / weight tuning. |
| `RIFTBOUND_GOALS` | `off` | No | Enables the goal-oriented strategist: once per turn an LLM emits a structured GoalSet that is compiled into a transient scoring-profile overlay biasing line selection (`ai_agent/docs/Goal_Oriented_Strategist.md`). Requires `RIFTBOUND_SEARCH=on`; ignored under `RIFTBOUND_SEARCH_ARGMAX`. Off keeps the proven base-profile search as the floor. |
| `RIFTBOUND_REASONER` | `off` | No | Enables the Phase-3 Reasoner pre-search handshake (`POST /reason`). Requires `RIFTBOUND_SEARCH=on` and `RIFTBOUND_SEARCH_ARGMAX=off`. The Reasoner can either commit a complete engine-registered line directly or emit a non-empty GoalSet overlay for the final search. |
| `RIFTBOUND_REASONER_MODEL` | (falls back to `RIFTBOUND_STRATEGIST_MODEL`, then `RIFTBOUND_AI_MODEL`) | No | Model used by the Reasoner think/terminal loop. Use this to try a stronger model for live investigation without changing the Actor/Planner defaults. |
| `RIFTBOUND_REASONER_NODE_BUDGET` | `1500` | No | Per-turn live-tool node budget shared by `search_for` and `deepen`. Exhaustion forces the Reasoner to terminate or fall back to base search. |
| `RIFTBOUND_REASONER_TIME_BUDGET_MS` | `3000` | No | Per-turn live-tool engine-time budget in milliseconds. Combined with the node budget; whichever reaches zero first exhausts the tool budget. |
| `RIFTBOUND_ENGINE_PORT` | `8766` | No | Port Python live tools use for Godot's local `EngineServer` (`127.0.0.1:<port>`). Must match the engine-side value when changed. |
| `RIFTBOUND_ENGINE_TIMEOUT_S` | `8.0` | No | Python HTTP timeout for each live engine tool call. Transport errors fall back to the Phase-1 pre-computed corpus where possible. |
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
- `agent_search.log` records searched candidate lines, search stats, and goal
  overlay deltas. Reasoner runs also write tool traces, terminal outcomes,
  budget status, and fallback reasons here. It is written only when
  `RIFTBOUND_LOG_INPUTS=1` and `RIFTBOUND_SEARCH=on`; enable both when debugging
  search selection, `RIFTBOUND_GOALS`, or `RIFTBOUND_REASONER`.
- The Python service HTTP port is set by the `uvicorn ... --port` argument, not
  by an agent-side environment variable. The Godot client defaults to
  `AGENT_PORT := 8765` (`Scripts/AI/AIPlayer.gd`); change the uvicorn port and
  Godot's `RIFTBOUND_AGENT_PORT` together if you need a different service port.

### Example

```bash
# Staged pipeline with debug logging on a cheaper model
export OPENAI_API_KEY=sk-...
export RIFTBOUND_AI_MODEL=gpt-4o-mini
export RIFTBOUND_PIPELINE=staged
export RIFTBOUND_LOG_INPUTS=1
uvicorn ai_agent.main:app --port 8765 --reload
```

### Example (Azure OpenAI)

```bash
# Point the agent at an Azure AI Foundry deployment instead of the OpenAI API.
export RIFTBOUND_LLM_PROVIDER=azure
# Full v1 base URL (or the bare resource URL — /openai/v1 is appended if missing).
export AZURE_OPENAI_ENDPOINT=https://bryanbj-4475-resource.services.ai.azure.com/openai/v1
export AZURE_OPENAI_API_KEY=<your-azure-key>
# Model names are Azure *deployment* names here — name the deployment to match.
export RIFTBOUND_AI_MODEL=gpt-5.4
uvicorn ai_agent.main:app --port 8765 --reload
```

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/decision` | POST | Main entry — receives BriefState, returns Decision |
| `/goals` | POST | Pre-search handshake — receives BriefState, returns this turn's compiled goal overlay (empty unless `RIFTBOUND_GOALS=on`) |
| `/reason` | POST | Phase-3 pre-search handshake — receives BriefState, scout lines, and `root_state_hash`; returns `base_search_fallback`, a compiled overlay, or a committed verified line |
| `/health` | GET | Liveness check |
| `/legal_moves` | GET | Current enumerated legal moves (debug) |
| `/state` | GET | Full board state text (debug) |
| `/card/{id}` | GET | Card definition lookup |
| `/rule?q=...` | GET | Rules passage search |
| `/position` | GET | Heuristic position evaluation |

## Architecture

```
Godot (GameController)
  └─ AIPlayer.gd
       ├─ GET /health at setup: adopt server search/goals flags
       ├─ optional TurnSearch scout + POST /goals or /reason before main search
       ├─ EngineServer.gd: local /engine/simulate + /engine/search for live tools
       └─ POST /decision with BriefState and candidate lines
             │
             ▼
        FastAPI (main.py)
             ├─ agent.py: legacy loop, line selector, goal overlay, Reasoner runner
             ├─ reasoner.py / reasoner_context.py: ReAct loop + verified registry
             ├─ engine_client.py / tool_budget.py: live engine calls + caps
             ├─ planner.py / strategist.py: cached per-turn LLM stages
             ├─ skills.py: read tools, simulations, scout search context
             └─ memory.py / capture.py: SQLite decision and tuning data
```

## Search, goals, and Reasoner modes

Search mode has three increasingly capable paths:

1. **Base search** (`RIFTBOUND_SEARCH=on`) — Godot runs `TurnSearch`, posts the
   candidate lines to `/decision`, and Python chooses one line or falls back to a
   validated move. This is the reliability floor.
2. **Goal strategist** (`RIFTBOUND_GOALS=on`) — before the main search, Godot can
   run a cheap base-profile scout and `POST /goals`. The returned overlay biases
   the final `TurnSearch`; `/decision` reuses the same GoalSet for server-side
   re-ranking. This requires search mode and is disabled by argmax mode.
3. **Phase-3 Reasoner** (`RIFTBOUND_REASONER=on`) — Godot runs the scout and
   `POST /reason` with the current `root_state_hash`. The Reasoner uses
   request-scoped live tools (`search_for`, `deepen`, `simulate_*`) against
   Godot's pinned `EngineServer` state. It terminates as one of:
   - `line`: commit a complete, engine-registered canonical line by `line_id`.
   - `goals`: return a strict 1-4 goal overlay for the final search.
   - `base_search_fallback`: run the normal base-profile search.

Committed Reasoner lines are never raw model-authored scripts. `TurnSearch` and
the registry provide canonical moves, `move_contexts`, `expected_pre_hashes`,
`root_state_hash`, `complete`, and `terminal_reason`. `AIPlayer.gd` checks the
root hash before step 0 and each step's pre-hash during replay; if the opponent
interacts or the state diverges, the line is dropped and the agent replans from
the live state. Budget-cutoff or incomplete lines can be investigated but are not
committable.

### Live engine tool runbook

```bash
# Terminal 1: start the Python service with search + Reasoner enabled.
export OPENAI_API_KEY=sk-...
export RIFTBOUND_SEARCH=on
export RIFTBOUND_REASONER=on
export RIFTBOUND_LOG_INPUTS=1
uvicorn ai_agent.main:app --port 8765 --reload

# Terminal 2: launch Godot normally.
# AIPlayer starts EngineServer on 127.0.0.1:8766 by default.
```

Operational constraints:

- `RIFTBOUND_REASONER` is ignored unless `RIFTBOUND_SEARCH=on` and
  `RIFTBOUND_SEARCH_ARGMAX=off`; `/health` exposes `reasoner_enabled` so Godot
  can mirror the server's actual mode.
- `RIFTBOUND_ENGINE_PORT` is shared by Python (`engine_client.py`) and Godot
  (`AIPlayer.gd` / `EngineServer.gd`). Change both environments together.
- Set engine-side `RIFTBOUND_ENGINE_SERVER=0` only when intentionally testing the
  Phase-1 fallback path. Live `search_for` / `deepen` calls need the server.
- `EngineServer` operates only on a cloned, pinned decision state and runs heavy
  `MoveSimulator` / `TurnSearch` work on a worker thread; the main loop only
  pumps HTTP.
- The engine pin is decision-scoped and cleared when a line commits, falls back,
  or the `/decision` request finishes. A `/reason` call without a
  `root_state_hash` deliberately returns `base_search_fallback`.

Troubleshooting quick checks:

| Symptom | Check |
|---|---|
| `/health` says `reasoner_enabled=false` | Confirm `RIFTBOUND_SEARCH=on`, `RIFTBOUND_REASONER=on`, and `RIFTBOUND_SEARCH_ARGMAX` is off in the Python service environment. |
| Reasoner tool calls report engine unreachable | Confirm Godot is running, `RIFTBOUND_ENGINE_SERVER` is not falsey, and Python/Godot agree on `RIFTBOUND_ENGINE_PORT` (default `8766`). |
| Reasoner returns `base_search_fallback` | Inspect `agent_search.log` for `fallback_reason`, budget exhaustion, terminal validation errors, or missing/changed `root_state_hash`. |
| A committed line stops mid-turn | This is expected when pre-hashes diverge after opponent interaction; `AIPlayer.gd` drops the line and replans or reactive-searches from the live window. |

## File Structure

```
ai_agent/
  __init__.py          Package marker
  schemas.py           Pydantic models: BriefState, Decision, Move, GoalSet
  prompts/             Static Markdown prompt modules loaded by name
  system_prompt.py     Prompt module assembly + keyword / goal vocabulary blocks
  planner.py           Cached per-turn plan producer for staged mode
  strategist.py        Cached per-turn GoalSet producer for search goals
  reasoner.py          Phase-3 search-driving ReAct loop and terminal tools
  reasoner_context.py  Request-local verified-line registry and telemetry state
  tool_budget.py       Per-turn node/time budgets for live Reasoner tools
  engine_client.py     Python HTTP client for Godot EngineServer live tools
  goal_compiler.py     GoalSet -> transient scoring-profile overlay
  skills.py            Read + helper skill implementations
  agent.py             Legacy reasoning loop, search line selector, fallbacks
  main.py              FastAPI service, env flags, logging, capture hooks
  memory.py            SQLite episodic event log
  capture.py           Search/tuning dataset persistence helpers
  agent_memory.db      Created at runtime (gitignored)
```

## Editing prompts

Static, placeholder-free prompt text lives in `ai_agent/prompts/*.md` and is
loaded with `load_prompt("<name>")` from `ai_agent/prompts/__init__.py`. Edit
those Markdown files when changing stable wording for the Actor, Planner,
Strategist, or line-selector retry prompts; `ai_agent/prompts/README.md` maps
each file to the Python module that loads it.

Keep runtime-specific prompts in code when they interpolate board state, legal
move ids, tool results, or schema context. `system_prompt.py` still owns dynamic
assembly: it includes core modules on every decision, conditionally adds combat /
priority / mulligan modules, injects only keywords visible in the current
`BriefState`, and generates the Strategist goal vocabulary from the compiler's
allowlists.

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
later score tuning (see `docs/Statistical_Analysis_Storage.md`). Post-game
analyst design (counterfactual missed wins / later goals, hypothesis loop):
`docs/LLM_Data_Analysis_Loop.md`.

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
| `RIFTBOUND_GOALS_SCOUT` | `on` | When goals are enabled, run a cheap base-profile scout search before `POST /goals` and send the top lines so the Strategist grounds goals in real candidate lines. Set to `0`, `false`, `no`, or `off` to disable the scout and use a snapshot-only strategist. |
| `RIFTBOUND_SELFPLAY_CAPTURE` | (unset) | When set (a log path, or `1`/`on` for the default `res://out/selfplay_capture.jsonl`), run fully offline: compute argmax locally, skip the server, and append every server-bound payload to the JSONL log for `import_selfplay_logs.py`. Forces search mode on. |
| `RIFTBOUND_ENGINE_SERVER` | `on` | Starts the local Godot `EngineServer` for Python live tools unless set to `0`, `false`, `no`, or `off`. Offline capture mode never starts it. |
| `RIFTBOUND_ENGINE_PORT` | `8766` | Port used by Godot's `EngineServer`; must match Python's `RIFTBOUND_ENGINE_PORT`. |
| `RIFTBOUND_SELFPLAY_CAPTURE` | (unset) | When set (a log path, or `1`/`on` for the default `res://out/selfplay_capture.jsonl`), run fully offline: compute argmax locally, skip the server, and append every server-bound payload to the JSONL log for `import_selfplay_logs.py`. Forces search mode on. |

## AI Evaluation

Frozen-position evaluation lives under `Data/AI/Eval/` and `ai_agent/eval/`.

```bash
# Validate the 22 bootstrap positions and regenerate the catalog
python -m ai_agent.eval validate-corpus
python -m ai_agent.eval render-catalog

# Deterministic blocking suite (no API key)
python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/blocking.json

# Weekly positions + robustness transforms
python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/weekly.json

# Godot fixture host / RuleEvaluation suite
./Scripts/run_tcg_tests.sh RuleEvaluation
./Scripts/run_eval_position.sh --fixture res://Scripts/Tests/Tcg/fixtures/search_winning_line.json --mode search
```

Human-readable docs:
- `ai_agent/docs/AI_Evaluation_Position_Catalog.md` — every position, objective, desired result
- `ai_agent/docs/AI_Evaluation_Operations.md` — authoring, profiles, weekly/release ops

Default eval adapters are mocked for CI. Live LLM and full paired arena pilots are opt-in.
