# Reasoner Multi-Game Baseline Plan

Status: **Planning document** — Implementation work tracked separately.

## 1. Problem / Why

The Reasoner investigation tooling (`search_for`, `deepen`, live engine tools) exists and has deterministic unit tests, but we lack **live acceptance evidence that the system remains stable across full games**. Deterministic fixtures prove correctness for individual turns; multi-game baselines prove operational reliability:

- **Commit rate** — can the Reasoner consistently commit complete, legal lines when enabled?
- **Fallback rate** — how often does it drop to `SEARCH` mode (base argmax) due to budget exhaustion, API failures, or engine unavailability?
- **Hash divergence rate** — how often do `root_state_hash` or `expected_pre_hashes` mismatches force mid-line abandonment and replanning?

Without a baseline corpus, we cannot measure whether a later change improves or degrades live reliability. This baseline establishes the **operational floor** for Reasoner-enabled play before expanding the eval corpus, tuning prompts, or adding opponent modeling.

## 2. Relation to Eval Pipeline

This baseline is **separate from the eval manifests** (`python -m ai_agent.eval run`):

| Eval Manifests | Multi-Game Baseline |
|---|---|
| Fixed positions (`Data/AI/Eval/positions/*.json`) | Full games (start to finish or turn cap) |
| Decision quality on curated puzzles | Operational stability and commit reliability |
| Hard gold pass rate, trap rate, score alignment | Commit rate, fallback rate, hash divergence rate |
| Blocking/weekly gate (`blocking.json`, `decision-v2.json`) | Archived baseline corpus (one-time or periodic refresh) |
| Uses `EvalPositionRunner` (Godot fixture host) | Uses `SelfPlaySim.gd` or manual play vs human/heuristic |

Eval positions measure **"does the Reasoner make good decisions?"** The baseline measures **"does the Reasoner stay up and working?"** Both are load-bearing. The eval pipeline is the quality gate; this baseline is the **reliability checkpoint**.

Keep `RIFTBOUND_SEARCH=on` with **base argmax as the fallback floor**: if the Reasoner fails mid-turn, the system degrades safely to the proven `TurnSearch` argmax selector rather than crashing.

## 3. Success Criteria (Done)

Archive an N-game baseline run (where N ≥ 20 games, provisionally) that reports at least:

1. **Commit rate** — percentage of eligible Reasoner turns where a `commit_line` terminal successfully committed a complete, legal, hash-verified line.
2. **Fallback rate** — percentage of turns where the Reasoner returned `base_search_fallback` and dropped to the argmax line selector. Includes API failures (retry exhaustion), budget exhaustion, and missing `root_state_hash` cases.
3. **Hash diverge rate** — percentage of committed lines where `root_state_hash` or an `expected_pre_hash` mismatched during Godot replay, forcing line abandonment and replanning. This happens when the opponent interacts or engine state diverges mid-line.

**Denominator definition:** Count only turns where the Reasoner path was eligible (not forced/single-legal-move/mulligan/reactive-only windows where Reasoner is bypassed). Log exemptions separately.

**Acceptance threshold:** Archive the baseline with denominators, exemption counts, and failure breakdowns. Do **not** set a hard % gate yet — the baseline establishes what "normal" looks like. Outlier failure modes (e.g., 100% fallback) should block archival and require investigation first.

## 4. Proposed Method

### 4.1 Runner Choice

The repository already has two live-play mechanisms:

| Tool | Use Case |
|---|---|
| `SelfPlaySim.gd` | Headless AI-vs-AI bulk runs; both seats argmax (no Reasoner) by default |
| Manual play | Godot UI, human vs AI or heuristic vs AI; natural opponent interaction |

**Recommendation (Phase 1):** Use `SelfPlaySim.gd` with **one Reasoner seat and one base-argmax seat**. This avoids the Reasoner playing both sides (which would conflate its errors) and provides a real opponent that can interact and trigger hash divergence. Alternatively, manual play vs a human or heuristic opponent generates more realistic interaction at the cost of operator time.

**Phase 2 option (deferred):** If a dedicated "reliability runner" is required, create `Scripts/Tools/ReasonerBaselineSim.gd` — a variant of `SelfPlaySim` that runs one seat with `RIFTBOUND_REASONER=on` and logs Reasoner-specific telemetry (committed line sources, fallback reasons, hash divergence events). Prefer reusing the existing tool first.

### 4.2 Configuration

#### Environment (Godot side)
```bash
export RIFTBOUND_SEARCH=on
export RIFTBOUND_REASONER=on
export RIFTBOUND_ENGINE_SERVER=on
export RIFTBOUND_ENGINE_PORT=8766
export RIFTBOUND_AI_THINK_DELAY=0
# Optional: write detailed Reasoner telemetry to agent_search.log
export RIFTBOUND_LOG_INPUTS=1
```

#### Environment (Python agent service)
```bash
export OPENAI_API_KEY=sk-...
export RIFTBOUND_SEARCH=on
export RIFTBOUND_REASONER=on
export RIFTBOUND_SEARCH_ARGMAX=off
export RIFTBOUND_LOG_INPUTS=1
export RIFTBOUND_DB_PATH=ai_agent/reasoner_baseline.db
export RIFTBOUND_DATA_ORIGIN=baseline_live
uvicorn ai_agent.main:app --port 8765
```

#### Run Command (example with SelfPlaySim)
```bash
<godot> --headless --path . --script res://Scripts/Tools/SelfPlaySim.gd -- \
  --games 20 --seed 5000 --turn-cap 100 \
  --p1-profile res://Data/AI/scoring_profile.json \
  --p2-profile res://Data/AI/scoring_profile.json
```

**Seat assignment:** If using `SelfPlaySim`, the Reasoner-enabled agent service runs for **both** seats in the default config. To isolate one Reasoner seat vs one argmax seat, either:
- Run two separate agent services on different ports (`--p1-agent-url` / `--p2-agent-url` if those flags exist), OR
- Modify `SelfPlaySim` to pass a seat-specific flag to the agent, OR
- Use manual play where the AI seat is Reasoner-enabled and the human/heuristic opponent is not.

**First iteration:** Archive a baseline with both seats running the same Reasoner-enabled profile; note this in the corpus metadata. The commit/fallback/diverge rates still measure Reasoner operational health even when both seats use it.

### 4.3 Artifacts

Archive the following under `Data/AI/Baseline/reasoner-multi-game-YYYY-MM-DD/`:

1. **Run metadata:** `run_info.json` — date, commit SHA, model (`RIFTBOUND_REASONER_MODEL`), number of games, seed base, turn cap, deck configs.
2. **Game summaries:** `games.jsonl` — one line per game with `game_id`, `turns`, `winner`, `p1_score`, `p2_score`, per-game Reasoner stats if available.
3. **Aggregate metrics:** `baseline_summary.json` — total eligible turns (denominator), commit count/rate, fallback count/rate (broken down by reason), hash diverge count/rate.
4. **Telemetry logs:** `agent_search.log` (Reasoner tool traces, terminal outcomes), `agent_tools.log`, SQLite DB excerpt or full DB snapshot.
5. **Manual review notes:** `review_notes.md` — operator's observations, any anomalies, failure-mode examples.

**Schema example (`baseline_summary.json`):**
```json
{
  "run_date": "2026-09-25",
  "git_sha": "abc123...",
  "model": "gpt-4o",
  "games_completed": 20,
  "total_turns": 487,
  "eligible_reasoner_turns": 412,
  "exemptions": {
    "forced_single_move": 48,
    "mulligan": 15,
    "reactive_only": 12
  },
  "commit_count": 385,
  "commit_rate": 0.934,
  "fallback_count": 27,
  "fallback_rate": 0.066,
  "fallback_breakdown": {
    "budget_exhausted": 12,
    "api_failure_after_retries": 8,
    "missing_root_hash": 5,
    "terminal_validation_failed": 2
  },
  "hash_diverge_count": 18,
  "hash_diverge_rate": 0.047,
  "diverge_breakdown": {
    "root_mismatch_pre_step_0": 3,
    "pre_hash_mismatch_mid_line": 15
  }
}
```

## 5. Metrics Definition

### 5.1 Commit Rate

**Formula:**
```
commit_rate = (successful_commit_line_terminals) / (eligible_reasoner_turns)
```

**What counts:**
- **Numerator:** Turns where the Reasoner's `/reason` endpoint returned `terminal_kind="line"`, the committed `line_id` referenced a complete, legal, root-matched registry entry, and Godot accepted the line for replay.
- **Denominator:** Turns where the Reasoner path ran (not forced/single-legal-move, not mulligan, not a reactive-only window where the Reasoner is bypassed). See §5.4 for exemptions.

**Logged per turn:**
- `terminal_kind` (`line`, `goals`, `base_search_fallback`)
- `committed_line_id` (if `terminal_kind="line"`)
- `line_source` (scout, `search_for`, `deepen`)
- Acceptance outcome from Godot (`accepted`, `rejected_root_mismatch`, `rejected_illegal`)

### 5.2 Fallback Rate

**Formula:**
```
fallback_rate = (base_search_fallback_count) / (eligible_reasoner_turns)
```

**What counts:**
- **Numerator:** Turns where the Reasoner's internal controller returned `terminal_kind="base_search_fallback"` instead of `line` or `goals`. This is **not** a model-authored output; it is an internal fail-safe triggered by:
  - Budget exhaustion (node or time budget depleted before a terminal tool was called)
  - API failure after retry exhaustion (`RIFTBOUND_TRANSIENT_RETRIES`)
  - Engine unavailable (missing `root_state_hash`, EngineServer unreachable)
  - Terminal validation failed and retry budget exhausted
- **Denominator:** Same as commit rate.

**Logged per turn:**
- `fallback_reason` (enumeration: `budget_exhausted`, `api_failure`, `missing_root_hash`, `engine_unreachable`, `terminal_retries_exhausted`, `other`)
- Node/time budget remaining when fallback triggered
- Number of transient retries consumed

**Breakdowns:** Separate counts for each `fallback_reason` in the aggregate summary.

### 5.3 Hash Diverge Rate

**Formula:**
```
hash_diverge_rate = (lines_abandoned_due_to_hash_mismatch) / (committed_lines_attempted)
```

**What counts:**
- **Numerator:** Committed lines where Godot's replay detected a `root_state_hash` mismatch **before step 0** or an `expected_pre_hash` mismatch **during replay** (mid-line). When a mismatch is detected, `AIPlayer.gd` abandons the line and replans from the live state.
- **Denominator:** All turns where `terminal_kind="line"` and a committed line began replay (regardless of whether replay completed or diverged).

**Logged per committed line:**
- `root_state_hash` from the Reasoner's `/reason` response
- `expected_pre_hashes` array (one per step)
- Divergence event: `diverged=true`, `divergence_step` (0-indexed; -1 = root check before step 0), `expected_hash`, `actual_hash`
- Opponent action immediately before divergence (if available)

**Breakdowns:** Separate counts for root mismatches (before step 0) vs mid-line pre-hash mismatches.

### 5.4 Exemptions (Denominator Adjustments)

Some turns are **not eligible** for Reasoner decisions and should not count toward any rate denominator:

| Exemption | Reason |
|---|---|
| Forced / single legal move | Only one command is legal; no investigation needed |
| Mulligan | Pre-game mulligan phase; Reasoner does not run |
| Reactive-only window | The AI seat has only `pass` / `choose` prompts (no main-turn tactical decision) |
| Engine state unavailable | Godot could not pin a `root_state_hash` (engine bug or transient setup failure) |

**Logging:** Track exemption counts separately in `baseline_summary.json` under `exemptions` with clear labels. The eligible-turn denominator is:
```
eligible_reasoner_turns = total_turns - sum(exemptions)
```

### 5.5 Aggregate Summary Metrics

Beyond the three primary rates, log:

- **Total games completed** (finished with a winner or hit turn cap)
- **Average game length** (turns)
- **Total Reasoner tool calls** (`search_for`, `deepen`, `simulate_move`, `simulate_line`)
- **Successful tool call rate** (non-error tool responses / total tool calls)
- **Median and p95 decision latency** (time from `/reason` request to terminal response)
- **Token usage** (if captured; per-game and aggregate)
- **Goals emission count** (turns where `terminal_kind="goals"` with non-empty GoalSet)

These are diagnostic only; they do not have hard acceptance thresholds for the baseline.

## 6. Implementation Steps

### 6.1 Instrumentation (if gaps exist)

**Check existing telemetry:**
- `ai_agent/capture.py` — does `reasoner_decisions` table log `terminal_kind`, `fallback_reason`, and `committed` flag?
- `ai_agent/tool_log_fmt.py` — does `agent_search.log` record terminal outcomes, tool budgets, and fallback reasons?
- `Scripts/AI/AIPlayer.gd` — does hash divergence trigger a logged event (or is it silent)?

**Add missing telemetry:**
- If `AIPlayer.gd` hash checks are silent, add log statements for root mismatch and pre-hash mismatch with `[INFO]` or `[WARN]` severity.
- If `reasoner_decisions` lacks a `diverged` or `divergence_step` column, add them (or log divergence events to a separate `reasoner_divergences` table).
- Ensure `fallback_reason` is recorded in `reasoner_decisions` or `agent_search.log` with an enumeration (not free text).

### 6.2 Runner Script (Optional)

**Option A (reuse existing tool):** Run `SelfPlaySim.gd` with Reasoner-enabled agent service. No new script required.

**Option B (dedicated runner):** Create `Scripts/Tools/ReasonerBaselineSim.gd`:
- Extends `SelfPlaySim.gd` or reimplements a simpler single-profile runner.
- Logs Reasoner-specific events (committed line source, fallback reason, divergence) to a structured JSONL.
- Writes per-game summaries and an aggregate `baseline_summary.json`.

**Recommendation:** Start with Option A. Create Option B only if the existing tool's output is insufficient for metrics extraction.

### 6.3 Metrics Extraction Script

Create `ai_agent/baseline_report.py`:
- Reads `ai_agent/reasoner_baseline.db` (or a dedicated SQLite snapshot) + `agent_search.log`.
- Queries `reasoner_decisions` for terminal outcomes, fallback reasons, and committed line sources.
- Queries `games` and joins with turn-level telemetry to compute denominators.
- Parses hash divergence events from logs or a dedicated table.
- Outputs `baseline_summary.json` with the schema from §4.3.

**Key functions:**
```python
def compute_commit_rate(db_path: str) -> dict:
    # Returns {"eligible_turns": N, "commit_count": M, "commit_rate": M/N}
    pass

def compute_fallback_rate(db_path: str) -> dict:
    # Returns {"fallback_count": K, "fallback_rate": K/N, "breakdown": {...}}
    pass

def compute_hash_diverge_rate(db_path: str, log_path: str) -> dict:
    # Returns {"diverge_count": D, "diverge_rate": D/L, "breakdown": {...}}
    pass

def generate_baseline_summary(db_path: str, log_path: str, out_path: str):
    # Combines all metrics into baseline_summary.json
    pass
```

**Invocation:**
```bash
python -m ai_agent.baseline_report \
  --db ai_agent/reasoner_baseline.db \
  --log agent_search.log \
  --out Data/AI/Baseline/reasoner-multi-game-2026-09-25/baseline_summary.json
```

### 6.4 Archival

After a run completes:
1. Copy `ai_agent/reasoner_baseline.db` (or export relevant tables) to `Data/AI/Baseline/reasoner-multi-game-YYYY-MM-DD/baseline.db`.
2. Copy `agent_search.log`, `agent_tools.log` to the same directory.
3. Run `baseline_report.py` to generate `baseline_summary.json`.
4. Extract per-game summaries to `games.jsonl` (or generate from DB).
5. Write `run_info.json` (date, SHA, model, config).
6. Add `review_notes.md` with operator observations.

Commit the archive directory to the repository under `Data/AI/Baseline/` (or store externally if SQLite DB size is prohibitive; commit only the JSON summaries in that case).

### 6.5 Reporting and Review

**Generate a human-readable summary:**
```bash
python -m ai_agent.baseline_report \
  --db Data/AI/Baseline/reasoner-multi-game-2026-09-25/baseline.db \
  --log Data/AI/Baseline/reasoner-multi-game-2026-09-25/agent_search.log \
  --markdown Data/AI/Baseline/reasoner-multi-game-2026-09-25/summary.md
```

**Example `summary.md` output:**
```markdown
# Reasoner Multi-Game Baseline — 2026-09-25

**Run metadata:**
- Commit: `abc123...`
- Model: `gpt-4o`
- Games: 20 (all completed, 0 hit turn cap)
- Eligible Reasoner turns: 412

**Commit Rate:** 93.4% (385 / 412)
- Scout lines: 62%
- `search_for` results: 28%
- `deepen` results: 10%

**Fallback Rate:** 6.6% (27 / 412)
- Budget exhausted: 12
- API failure (retry exhaustion): 8
- Missing root hash: 5
- Terminal validation failed: 2

**Hash Diverge Rate:** 4.7% (18 / 385 committed lines)
- Root mismatch (before step 0): 3
- Pre-hash mismatch (mid-line): 15

**Exemptions:** 75 turns (forced: 48, mulligan: 15, reactive-only: 12)

**Tool usage:**
- Total tool calls: 1847
- Successful: 1803 (97.6%)
- `search_for`: 214
- `deepen`: 89
- `simulate_move`: 1328
- `simulate_line`: 216

**Decision latency:**
- Median: 2.4s
- p95: 6.8s

**Review notes:** See `review_notes.md`.
```

Review the summary for anomalies:
- **Commit rate < 80%** → investigate fallback reasons (budget too tight? API instability?)
- **Hash diverge rate > 20%** → check if opponent interaction is unusually high or if hash logic is broken
- **Fallback breakdown shows one dominant cause** → fix that cause before archiving the baseline

## 7. Acceptance Checklist

Operator-run checklist to mark the Notion task done:

- [ ] **Environment configured** — Godot and Python services running with `RIFTBOUND_REASONER=on`, `RIFTBOUND_ENGINE_SERVER=on`, correct ports.
- [ ] **N games completed** — At least 20 full games (or operator-approved N if 20 is too costly; document the choice).
- [ ] **Telemetry captured** — `reasoner_decisions`, `agent_search.log`, hash divergence events recorded.
- [ ] **Metrics extracted** — `baseline_report.py` (or equivalent) ran successfully and produced `baseline_summary.json`.
- [ ] **Denominators validated** — Eligible turn count, exemptions, and breakdowns are logged and reasonable.
- [ ] **No critical failure modes** — Commit rate is not 0%, fallback rate is not 100%, hash diverge rate is not 100% (any of these would indicate a broken system).
- [ ] **Artifacts archived** — All logs, DB snapshot, JSON summaries, and `review_notes.md` saved under `Data/AI/Baseline/reasoner-multi-game-YYYY-MM-DD/`.
- [ ] **Summary reviewed** — Operator (or another engineer) read the summary and noted any anomalies in `review_notes.md`.
- [ ] **Baseline committed** — Archive directory (or JSON summaries if DB is external) committed to the repository.

**Definition of done:** A complete, archived baseline corpus exists with documented commit/fallback/diverge rates, exemptions, and tool-usage diagnostics. Future changes can compare their metrics against this baseline to detect regressions.

## 8. Follow-Ups (Out of Scope)

These are **not** part of the baseline archive; each is a separate task:

1. **Expand eval corpus** — Add Reasoner-specific eval positions to `Data/AI/Eval/positions/` and manifests (e.g., `reasoner-live-smoke.json` already exists; expand to cover forced investigation, seeded lines, hash divergence edge cases).
2. **CI integration** — Run a small-N baseline as a weekly/release gate (similar to `weekly-engine.json` / `weekly-agent.json`). Fail the gate if commit rate drops below a threshold or fallback rate spikes.
3. **Staged vs legacy comparison** — Archive baselines for both `RIFTBOUND_PIPELINE=staged` and `RIFTBOUND_PIPELINE=legacy` to measure impact of the staged router/planner/actor split.
4. **Prompt tuning** — Use baseline tool-usage and fallback breakdowns to identify investigation gaps (e.g., "90% of `search_for` calls return empty results → prompt is too vague").
5. **SPRT weight promotion** — Use the archived baseline as the control arm for a Bernoulli SPRT self-play gate when testing Reasoner prompt or tool-budget changes (`ai_agent/eval/arena.py` helpers, `python -m ai_agent.eval sprt-report`).
6. **Opponent modeling extension** — After `simulate_opponent` / `branch` / `rollout` land (Toolkit Phase 5+), archive a separate multi-game baseline with those tools enabled.
7. **Memory track integration** — When `Memory_Roadmap.md` LTM work lands, measure how memory context affects commit/fallback rates in a follow-up baseline.
8. **Runbook documentation** — Extract operational lessons from `review_notes.md` and write a Reasoner operator runbook (setup, troubleshooting, how to read telemetry logs).

**Why these are out of scope:** The baseline establishes the reliability floor with the **current** Reasoner implementation. Extensions, tuning, and downstream gates depend on this baseline existing first.

## 9. Non-Goals

Explicit **non-goals** for this baseline (to avoid scope creep):

- **No corpus expansion** — We are not adding new eval positions or manifests here. Use existing tools (`SelfPlaySim`, manual play).
- **No prompt changes** — Archive the baseline with the current Reasoner prompts. Tuning happens separately after the baseline exists.
- **No model A/B testing** — Use one model (e.g., `gpt-4o`) for the baseline. Future baselines can compare models.
- **No SPRT self-play gate** — This baseline is the **measurement**, not the gate. SPRT follows in a later task.
- **No automated reliability monitor** — The baseline is a one-time (or periodic) manual run. CI integration is a separate follow-up.
- **No Memory track** — Reasoner runs with no persistent LTM context for this baseline. Memory integration is deferred.

## 10. Open Questions

- **How many games (N)?** Provisionally N ≥ 20. Adjust based on variance in the first pilot run (if commit rate is stable at N=10, use that; if it swings wildly, increase to N=50).
- **Which opponent?** SelfPlaySim default (base argmax) or manual human play? Recommendation: start with SelfPlaySim for reproducibility; optionally archive a second baseline with human opponents if operator time allows.
- **What commit rate is acceptable?** No hard gate yet — the first baseline establishes "normal." If commit rate < 50%, investigate before archiving (likely a system bug, not operational noise).
- **Should we archive failed games separately?** If a game crashes or hits an unhandled exception, log it in a `failed_games.jsonl` and exclude from the main metrics (do not silently fold failures into denominators).
- **Offline capture mode compatibility?** `RIFTBOUND_SELFPLAY_CAPTURE` bypasses the agent service. Reasoner cannot run without `/reason` HTTP round-trips, so offline capture is **incompatible** with Reasoner-enabled baselines. Document this constraint.

## 11. Related Docs

- `Deliberative_Reasoning_Toolkit.md` — Reasoner design and phasing
- `Reasoner_Investigation_Acceptance.md` — Phase 1–6 shipped capabilities, contracts
- `Reasoner_Investigation_Improvements.md` — Corrective plan (deterministic fixtures, behavioral acceptance §5.3)
- `AI_Evaluation_Operations.md` — Eval pipeline (not this baseline, but complementary)
- `Goal_Oriented_Strategist.md` — Goal overlay system (used by `terminal_kind="goals"`)
- `ai_agent/README.md` — Agent service flags, search modes, self-play runbook

**Positioning:** This plan is the **live acceptance + multi-game baseline metrics** checkpoint from the Notion task. Deterministic contracts (`Reasoner_Investigation_Improvements.md` §5.1–§5.2) already pass; this baseline extends acceptance to operational reliability across full games.
