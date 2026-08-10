# AI Evaluation Operations

How to author positions, run weekly/release evaluation, and promote failures.

## Layout

| Path | Purpose |
|---|---|
| `Data/AI/Eval/positions/*.json` | Version-controlled eval cases (source of truth) |
| `Scripts/Tests/Tcg/fixtures/*.json` | Engine game-state fixtures referenced by cases |
| `Data/AI/Eval/profiles/*.json` | Agent architecture profiles + ablations |
| `Data/AI/Eval/manifests/*.json` | Blocking / weekly / arena run manifests |
| `ai_agent/docs/AI_Evaluation_Position_Catalog.md` | Generated human-readable catalog (all lanes) |
| `ai_agent/docs/AI_Evaluation_Decision_Catalog_v2.md` | Curated contested agent decision-quality catalog |
| `Data/AI/Eval/runs/<run_id>/` | Generated results (`results.db`, `report.md`, `metrics.json`, JSONL) |
| `ai_agent/eval/` | Python schemas, runner, graders, arena helpers |
| `Scripts/Tools/EvalPositionRunner.gd` | Headless Godot fixture host |
| `Scripts/Tools/SelfPlaySim.gd` | Paired arena legs (`--pair-mode`, `--json-results`) |

## Authoring a position

1. Create or reuse a fixture under `Scripts/Tests/Tcg/fixtures/`.
2. Add a case JSON under `Data/AI/Eval/positions/` with:
   - `summary`, `objective`, `desired_result`
   - `fixture_path`, `acting_seat`, `decision_type`
   - `split` (`blocking` | `dev` | `sealed` | `challenge`)
   - **`eval_lane`**: `engine` (Godot contracts / search correctness) or `agent` (decision quality)
   - `label_tier` (`gold` | `silver` | `diagnostic`)
   - `fidelity_status` (`authoritative` | `fidelity_limited` | `excluded`)
   - `hard_invariants` and `acceptable_outcomes`
3. Validate and regenerate the catalog:

```bash
python -m ai_agent.eval validate-corpus
python -m ai_agent.eval render-catalog
```

Gold labels require deterministic engine outcomes or adjudicated acceptable sets. Silver labels (deeper search agreement) are diagnostic only.

**Do engine contracts need an LLM?** No. `eval_lane: engine` cases are graded from Godot TurnSearch / commit-reject / seeded search only.

## Agent smoke vs decision catalog v2

Easy / free-value agent positions are tagged `agent_smoke` (former decision-v1 set). They regress under Godot argmax with **no LLM**:

```bash
export GODOT=/Applications/Godot.app/Contents/MacOS/Godot   # or your binary
python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/agent-argmax-smoke.json
```

`weekly-agent.json` also covers the agent lane (argmax by default). Contested decision-quality puzzles live in [AI_Evaluation_Decision_Catalog_v2.md](AI_Evaluation_Decision_Catalog_v2.md):

```bash
python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/decision-v2.json
```

Uses `baseline-argmax` by default for labels/smoke. For live Reasoner, set the manifest `profiles` to `["reasoner-default"]`. Each run writes `metrics.json` (hard gold pass rate, trap rate, cost, …) beside `report.md`.

## Profiles and ablations

Each agent architecture declares its own components. Shared position / validity / robustness / arena tests stay architecture-independent.

Example Reasoner ablations live in `Data/AI/Eval/profiles/reasoner-default.json`:
- `no-reasoner`
- `no-tools`
- `shuffled-scout`

A planner–executor or policy-only stack would declare different component comparisons in its own profile file.

## Running evaluation

### Every relevant change (blocking, offline)

```bash
python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/blocking.json
```

Uses `baseline-argmax-mock` — no Godot, no API key. Validates schemas/graders/report plumbing.

### Engine contracts (real Godot, no LLM)

```bash
export GODOT=/Applications/Godot.app/Contents/MacOS/Godot   # or your binary
python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/engine-contract-smoke.json
```

`eval_lanes: ["engine"]` only — hash rejects, budget cutoffs, seeded lines, TT completeness, greedy discard, etc.

### Agent decision quality without LLM (Godot argmax baseline)

```bash
python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/agent-argmax-smoke.json
```

### Live Reasoner decision quality (Godot + LLM)

```bash
export GODOT=...
# Prefer repo-root .env (OPENAI_API_KEY / Azure vars). Eval loads it automatically.
python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/reasoner-live-smoke.json
# A/B current vs investigation redesign profile (gold/trap + investigation metrics)
python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/reasoner-investigate-accept.json
```

### Investigation-quality reports

Eval `metrics.json` now includes investigation aggregates (`novel_investigation_rate`,
`local_fork_rate`, `scout_agreement_rate`, …) when Reasoner telemetry is present.

```bash
# Summarize an existing run
python -m ai_agent.eval investigate-report --run-dir Data/AI/Eval/runs/reasoner-live-smoke
# Archive a §5.3-shaped baseline stub (or pass --from-run-dir for a live run)
python -m ai_agent.eval investigate-baseline
# SPRT strength report from arena pair JSONL
python -m ai_agent.eval sprt-report --pairs-jsonl /tmp/pairs.jsonl --out Data/AI/Eval/runs/sprt/report.md
```

`eval_lanes: ["agent"]` only — e.g. win-from-seven, turn8 continuation, card-play preferences. Spawns `EvalPositionRunner --mode agent_ready`, pins `EngineServer`, then runs in-process `run_reasoner`.

#### Rate limits

Trials run sequentially, but each one spends several tool rounds against the API, so a small quota trips its per-minute limit well before the run finishes. Two controls:

- **Pacing** — the manifest's `throttle_ms` sleeps between LLM-backed trials (`reasoner-live-smoke` uses 3000). Override per run with `RIFTBOUND_EVAL_THROTTLE_MS=8000`. Non-LLM adapters ignore it, so engine-lane runs stay fast.
- **Backoff** — `reasoner-default.json` sets `RIFTBOUND_TRANSIENT_RETRIES=6`, `RIFTBOUND_TRANSIENT_BACKOFF_S=2.0`, and `RIFTBOUND_TRANSIENT_BACKOFF_MAX_S=60.0`. The last one matters most: live play caps a single wait at 10s so a retry never outlives Godot's decision timeout, but a batch run has no such deadline and can honor the provider's full `Retry-After`.

If 429s persist, cut volume rather than waiting longer: drop `repeats` to 1, narrow `splits` to `blocking`, or run `weekly-agent.json` under `baseline-argmax` to confirm the positions themselves are healthy before spending tokens.

### Weekly suites

```bash
# Engine contracts + transforms (no LLM)
python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/weekly-engine.json
# Agent decision positions under argmax (swap profile to reasoner-default for live LLM)
python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/weekly-agent.json
```

### Single-position Godot host

```bash
./Scripts/run_eval_position.sh \
  --fixture res://Scripts/Tests/Tcg/fixtures/search_winning_line.json \
  --mode search
./Scripts/run_tcg_tests.sh RuleEvaluation
```

### Arena pilot expansion

```bash
python -m ai_agent.eval expand-arena --manifest Data/AI/Eval/manifests/arena-pilot.json
```

Paired legs can be driven with SelfPlaySim:

```bash
# Leg A
RIFTBOUND_AI_THINK_DELAY=0 RIFTBOUND_SELFPLAY_CAPTURE=1 \
  <godot> --headless --script res://Scripts/Tools/SelfPlaySim.gd -- \
  --pair-mode --seed 1000 --first-player 0 --candidate-seat 0 \
  --p1-profile res://Data/AI/scoring_profile.json \
  --p2-profile res://Data/AI/scoring_profile.json \
  --json-results /tmp/arena.jsonl --game-session-id arena-pair-1000-a

# Leg B swaps seats / decks / first player
```

Sequential SPRT release gating is deferred until pilot variance is measured. Pair-level Wilson intervals are available via `ai_agent.eval.arena.analyze_pairs`.

## Interpreting reports

`Data/AI/Eval/runs/<run_id>/report.md` separates:
- hard validity failures
- gold decision failures
- silver/search diagnostics
- trajectory warnings
- cost / timeout metrics

`metrics.json` (also under `summary.metrics` in `manifest.json`) reports:
- `hard_gold_pass_rate` / `easy_gold_pass_rate` — authoritative gold by difficulty
- `trap_rate` — attractive wrong-line hits on cases with `trap_outcomes`
- `validity_fail_rate`, `timeout_rate`, `trajectory_warn_rate`
- latency / token aggregates

Do not collapse these into one quality score. A gain on easy slices cannot hide a legality or terminal-tactics regression.

## Promoting a real failure

1. Capture the fixture / brief state.
2. Add a new case under `dev` (or `blocking` if it is a hard invariant).
3. Never silently rewrite prior gold labels after a scoring-profile change — bump label version / provenance instead.
4. Re-run `validate-corpus` and `render-catalog`.

## Tests

```bash
python -m pytest ai_agent/tests/test_eval_infra.py -q
./Scripts/run_tcg_tests.sh RuleEvaluation
# Optional Godot-backed smoke (requires GODOT):
python -m pytest ai_agent/tests/test_eval_engine.py -q
```

Default Python eval tests use the mock adapter and never require an API key.
Engine/reasoner manifests exercise the real agent path.
