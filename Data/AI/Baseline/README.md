# Reasoner Multi-Game Baseline

Operational reliability baseline for the Reasoner investigation tooling. Measures commit rate, fallback rate, and hash divergence rate across N full games.

## Quick Start

### 1. Prerequisites

**Godot side (engine):**
```bash
export RIFTBOUND_SEARCH=on
export RIFTBOUND_REASONER=on
export RIFTBOUND_ENGINE_SERVER=on
export RIFTBOUND_ENGINE_PORT=8766
export RIFTBOUND_AI_THINK_DELAY=0
export RIFTBOUND_LOG_INPUTS=1
```

**Python side (agent service):**
```bash
export OPENAI_API_KEY=sk-...
export RIFTBOUND_SEARCH=on
export RIFTBOUND_REASONER=on
export RIFTBOUND_SEARCH_ARGMAX=off
export RIFTBOUND_LOG_INPUTS=1
export RIFTBOUND_DB_PATH=ai_agent/reasoner_baseline.db
export RIFTBOUND_DATA_ORIGIN=baseline_live

# Start the agent service
uvicorn ai_agent.main:app --port 8765
```

### 2. Run N Games

**Small smoke test (N=2):**
```bash
<godot> --headless --script res://Scripts/Tools/SelfPlaySim.gd -- \
  --games 2 --seed 5000 --turn-cap 100 \
  --p1-profile res://Data/AI/scoring_profile.json \
  --p2-profile res://Data/AI/scoring_profile.json
```

**Full baseline (N=20):**
```bash
<godot> --headless --script res://Scripts/Tools/SelfPlaySim.gd -- \
  --games 20 --seed 5000 --turn-cap 100 \
  --p1-profile res://Data/AI/scoring_profile.json \
  --p2-profile res://Data/AI/scoring_profile.json
```

Both seats will use the Reasoner-enabled agent service by default. For more controlled testing, run two separate agent services on different ports using `--p1-agent-url` and `--p2-agent-url` flags (one Reasoner-enabled, one base argmax).

### 3. Generate Report

```bash
python -m ai_agent.baseline_report \
  --db ai_agent/reasoner_baseline.db \
  --log agent_search.log \
  --out Data/AI/Baseline/reasoner-multi-game-$(date +%Y-%m-%d)/baseline_summary.json \
  --markdown Data/AI/Baseline/reasoner-multi-game-$(date +%Y-%m-%d)/summary.md \
  --git-sha $(git rev-parse HEAD) \
  --model gpt-4o
```

### 4. Archive Results

```bash
# Set the baseline date
BASELINE_DIR="Data/AI/Baseline/reasoner-multi-game-$(date +%Y-%m-%d)"

# Copy database and logs
cp ai_agent/reasoner_baseline.db $BASELINE_DIR/baseline.db
cp agent_search.log $BASELINE_DIR/
cp agent_tools.log $BASELINE_DIR/ 2>/dev/null || true

# Create run_info.json
cat > $BASELINE_DIR/run_info.json <<EOF
{
  "date": "$(date +%Y-%m-%d)",
  "git_sha": "$(git rev-parse HEAD)",
  "model": "gpt-4o",
  "games": 20,
  "seed_base": 5000,
  "turn_cap": 100,
  "deck_p1": "res://Data/Decks/starter-deck-p2.json",
  "deck_p2": "res://Data/Decks/starter-deck-p2.json"
}
EOF

# Add manual review notes
cat > $BASELINE_DIR/review_notes.md <<EOF
# Baseline Review Notes

**Operator:** [Your Name]
**Date:** $(date +%Y-%m-%d)

## Observations

- [Note any anomalies, failure patterns, or interesting behaviors]
- [Commit rate within expected range?]
- [Fallback reasons distribution?]
- [Hash divergence patterns?]

## Issues Encountered

- [Document any runtime issues, crashes, or blockers]

## Follow-up Actions

- [Any recommended changes or investigations]
EOF

# Commit the archive
git add $BASELINE_DIR/
git commit -m "Archive Reasoner multi-game baseline $(date +%Y-%m-%d)"
```

## Interpreting Results

### Commit Rate
**Definition:** Percentage of eligible Reasoner turns where a complete, legal, hash-verified line was committed.

**Formula:** `commit_rate = successful_commits / eligible_turns`

**What's good:** >80% indicates the Reasoner can consistently produce valid lines.

**What's bad:** <50% suggests systematic issues (budget too tight, investigation failures, or engine bugs).

### Fallback Rate
**Definition:** Percentage of turns where the Reasoner returned `base_search_fallback` instead of a line or goals.

**Formula:** `fallback_rate = fallback_count / eligible_turns`

**Common reasons:**
- `budget_exhausted` — investigation ran out of time/nodes
- `api_failure_after_retries` — LLM service unavailable
- `missing_root_hash` — engine state pinning failed
- `terminal_retries_exhausted` — validation loop exhausted

**What's good:** <10% indicates stable operation.

**What's bad:** >20% suggests environmental issues (API instability) or insufficient budgets.

### Hash Diverge Rate
**Definition:** Percentage of committed lines where hash mismatches forced mid-line abandonment.

**Formula:** `diverge_rate = diverge_count / committed_lines_attempted`

**Types:**
- `root_mismatch_pre_step_0` — state diverged before executing the line
- `pre_hash_mismatch_mid_line` — opponent interacted during line execution

**What's good:** <10% is normal opponent interaction.

**What's bad:** >30% suggests hash logic bugs or opponent thrashing.

### Exemptions
Turns not eligible for Reasoner decisions:
- `forced_single_move` — only one legal move
- `mulligan` — pre-game mulligan phase
- `reactive_only` — only prompts/passes available

These are excluded from rate denominators.

## Troubleshooting

### All fallbacks are "missing_root_hash"
**Cause:** Engine server not running or EngineServer disabled.

**Fix:** Verify `RIFTBOUND_ENGINE_SERVER=on` and port 8766 is accessible.

### High API failure rate
**Cause:** LLM service rate limits or network issues.

**Fix:** Increase `RIFTBOUND_TRANSIENT_RETRIES` or use a higher tier API key.

### Zero commits
**Cause:** Reasoner not enabled or agent service misconfigured.

**Fix:** Verify `/health` endpoint shows `reasoner_enabled: true` and `RIFTBOUND_REASONER=on` on both sides.

### Games hang or timeout
**Cause:** Agent service crashed or decision loop stalled.

**Fix:** Check `agent_search.log` for exceptions. Restart the service and reduce `--games` for smoke testing.

## Acceptance Checklist

Before archiving a baseline, verify:

- [ ] N ≥ 20 games completed (or operator-approved alternative)
- [ ] `baseline_summary.json` generated successfully
- [ ] Commit rate is not 0%
- [ ] Fallback rate is not 100%
- [ ] Hash diverge rate is not 100%
- [ ] Denominators and exemptions are logged
- [ ] `review_notes.md` completed with operator observations
- [ ] All artifacts archived under `Data/AI/Baseline/`

## Related Documentation

- [Reasoner Multi-Game Baseline Plan](ai_agent/docs/Reasoner_Multi_Game_Baseline_Plan.md) — full specification
- [Deliberative Reasoning Toolkit](ai_agent/docs/Deliberative_Reasoning_Toolkit.md) — Reasoner design
- [AI Evaluation Operations](ai_agent/docs/AI_Evaluation_Operations.md) — eval pipeline (complementary)
- [Agent README](ai_agent/README.md) — agent service flags and self-play runbook
