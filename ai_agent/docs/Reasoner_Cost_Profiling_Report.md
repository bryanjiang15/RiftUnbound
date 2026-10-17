# Reasoner Cost Profiling Report

**Date:** 2026-10-17  
**Analysis type:** Static code analysis + architecture review  
**Context:** Cost profiling to inform N=20-game baseline feasibility

---

## Executive Summary

The Reasoner's per-decision cost is dominated by **large prompt payloads** (system prompts + tool schemas + scout lines + game state) sent on every model call within the ReAct loop. A typical decision makes **3-5 model calls** with input prompts of **8K-15K tokens** each, accumulating **30K-75K input tokens** per decision across all ReAct iterations.

**Top 3 Cost Drivers (by token volume):**
1. **System prompt assembly** (~4K-8K tokens/call): Reasoner role + discipline + few-shot + dynamic rules
2. **Tool schemas** (~3K-4K tokens/call): 14 tool definitions × ~200-300 tokens each
3. **Scout line payload** (~2K-10K tokens/call, highly variable): Depends on line count, move length, and score breakdown detail

**Top 3 Recommendations:**
1. **Enable prompt caching** (OpenAI Prompt Caching or Claude Prompt Cache): 50-75% input token savings by caching system + tools
2. **Reduce scout line detail** in the initial payload: 20-40% input token savings by deferring verbose metadata to tool calls
3. **Tighten ReAct loop budget** (REASONER_MAX_TOOL_ROUNDS 6→4): 15-25% total cost savings with minimal quality impact for deterministic games

---

## 1. Cost Breakdown (Per Decision)

### 1.1 Token Accounting

Based on static analysis of `reasoner.py`, the Reasoner makes multiple model calls per decision within a ReAct loop. Each call includes:

| Component | Size (tokens, estimated) | Frequency | Notes |
|-----------|-------------------------|-----------|-------|
| **System prompt** | 4,000 - 8,000 | Every call | Includes role, discipline, few-shot, rules modules |
| **Tool schemas** | 3,000 - 4,000 | Every call | 14 tools × ~250 tokens avg |
| **User message (turn context)** | 1,000 - 3,000 | First call only | Memory timeline + brief state + root hash + scout baseline |
| **Scout line payload** | 2,000 - 10,000 | First call only | Variable: 5-20 lines × ~200-500 tokens/line |
| **Tool result** | 500 - 3,000 | Per tool round | Varies by tool: `search_for` heavy, `get_keyword` light |
| **Feedback envelope** | 200 - 500 | Per search tool | Advisory guidance after `search_for`/`deepen` |
| **Assistant reasoning** (output) | 200 - 800 | Per call | Model's <think> + tool call args |

**Per-call input token estimate:**
- **First call:** 10,000 - 25,000 tokens (system + tools + context + scout lines)
- **Subsequent calls:** 7,000 - 12,000 tokens (system + tools + tool result + feedback)

**Typical decision flow (3 model calls):**
1. First call with full context → tool call (`evaluate_position` or `search_for`)
2. Tool result → tool call (`deepen` or `search_for`)
3. Tool result → terminal tool call (`commit_line`)

**Token total per decision (estimated):**
- **Input tokens:** 24,000 - 60,000 (mean ~40,000)
- **Output tokens:** 600 - 2,400 (mean ~1,200)
- **Total tokens:** ~25,000 - 62,000 (mean ~41,200)

**Cost estimate (GPT-4o rates as of 2026-10-17):**
- Input: $5.00/1M tokens → ~$0.20 per decision
- Output: $15.00/1M tokens → ~$0.018 per decision
- **Total: ~$0.22 per decision**

**N=20 baseline projection:**
- Assume 20 games × 25 turns/game × 0.8 eligible Reasoner turns = **400 decisions**
- **Total cost: ~$88** for N=20 (input-heavy)

### 1.2 Model Call Distribution

From `reasoner.py` line 822-840, the ReAct loop runs up to `REASONER_MAX_TOOL_ROUNDS = 6` iterations. Analysis of terminal conditions:

| Decision outcome | Typical model calls | Frequency (estimated) | Notes |
|------------------|---------------------|----------------------|-------|
| **Commit scout leader** | 2-3 | 40-60% | Minimal investigation; passes novelty gate quickly |
| **Commit after investigation** | 3-5 | 30-40% | 1-2 `search_for`/`deepen` rounds before commit |
| **Fallback to SEARCH** | 4-6 | 5-10% | Exhausts budget or retries; falls back to base argmax |
| **Emit goals** | 3-4 | 5-10% | Strategic goals when no complete line satisfies |

**Mean model calls per decision:** ~3.5  
**p95 model calls:** ~5-6

### 1.3 Latency Breakdown

From `reasoner.py` line 752-799 (telemetry capture):

| Component | Median latency (est.) | p95 latency (est.) | Notes |
|-----------|----------------------|-------------------|-------|
| **Model orchestration** | 1.5-3.0s | 4-8s | ReAct loop overhead (excluding engine) |
| **Engine tools** | 0.5-2.0s | 3-6s | `search_for`, `deepen` (EngineServer round-trip) |
| **Total Reasoner latency** | 2.4s | 6.8s | From baseline plan doc example |

Engine latency is **logged separately** (line 755-756: `engine_latency_ms` vs `reasoner_latency_ms`), so model+orchestration overhead is the **reasoner_latency - engine_latency** delta.

---

## 2. Prompt Component Sizing

### 2.1 System Prompt (per call)

From `reasoner.py` line 685-689:

```python
system = f"{_ROLE}\n\n{_DISCIPLINE}\n\n{_FEW_SHOT}\n\n{rules}".strip()
```

| Module | File | Size (chars) | Est. tokens | Notes |
|--------|------|-------------|-------------|-------|
| `reasoner_role_base` | `prompts/reasoner_role_base.md` | ~4,000 | ~1,200 | EVIDENCE ORDER, tool discipline |
| `reasoner_output_discipline_think` | `prompts/reasoner_output_discipline_think.md` | ~1,400 | ~420 | Investigation state machine |
| `reasoner_few_shot_traces` | `prompts/reasoner_few_shot_traces.md` | ~1,200 | ~360 | 3 worked examples |
| `rules` (dynamic) | `system_prompt.build_system_prompt_from_modules` | ~8,000-15,000 | ~2,400-4,500 | goal_and_role, core_rules, keywords_in_play, goal_vocabulary |

**Total system prompt:** ~14,600-21,600 characters → **~4,400-6,500 tokens**

**Rules module breakdown** (from `system_prompt.py` line 686-688):
- `goal_and_role`: ~3,200 chars (~960 tokens)
- `core_rules`: ~3,600 chars (~1,080 tokens)
- `keywords_in_play`: Variable, 0-20 keywords × ~100-200 chars each (~0-1,500 tokens)
- `goal_vocabulary`: Only when goals present (~0-500 tokens)

### 2.2 Tool Schemas (per call)

From `reasoner.py` line 291-299, the Reasoner uses a **subset** of `agent.TOOLS`:

```python
tools = [
    tool
    for tool in agent_module.TOOLS
    if tool.get("function", {}).get("name") in REASONER_TOOL_NAMES
]
return tools + _terminal_tool_schemas()
```

**REASONER_TOOL_NAMES** (line 35-47): 12 investigation tools  
**+ _terminal_tool_schemas()** (line 208-289): 2 terminal tools (`commit_line`, `emit_goals`)

**Total: 14 tools** × ~250-300 tokens each = **~3,500-4,200 tokens**

**Heaviest schemas:**
- `emit_goals` terminal tool: ~800 tokens (nested goal_set schema with enum constraints)
- `search_for` / `deepen`: ~400-500 tokens (complex parameters with examples)
- `simulate_line`: ~350 tokens (array of move objects)

### 2.3 Scout Line Payload (first call only)

From `reasoner.py` line 690-714:

```python
scout_block = (
    json.dumps(_render_scout_lines(known_lines), indent=2, default=str)
    if known_lines
    else "(none)"
)
```

**Per-line overhead** (from `_render_scout_lines` line 380-459):
- `line_id`, `steps` (array of commands + context), `strategic_prefix_moves`
- `deepen_hint` (nested object with prefix options)
- `cluster_key`, `cluster_size`, `score_band`, `top_score_terms` (dict)
- `resolved_state` (delta with ~10 keys, values variable)
- `complete`, `terminal_reason`, `contested`, `opponent_windows` count
- Optional: `score`, `risk_adjusted_score`, `risk_penalty`, `risk_adjustment_method`, `risk` summary

**Token estimate per line:**
- Minimal line (2-3 moves, incomplete): ~150-200 tokens
- Typical line (4-6 moves, complete, score breakdown): ~300-500 tokens
- Heavy line (8-10 moves, risk expanded, large resolved_state): ~600-1,000 tokens

**Scout line count** (from TurnSearch beam): **5-20 lines** typical (top_n from `search_turn`)

**Total scout payload:** 5 lines × 300 tokens = **1,500 tokens** (light) to 20 lines × 600 tokens = **12,000 tokens** (heavy)

**Mean estimate:** ~10 lines × 400 tokens = **~4,000 tokens**

### 2.4 Tool Results (per round)

| Tool name | Typical result size | Notes |
|-----------|-------------------|-------|
| `evaluate_position` | ~400-800 tokens | Structured summary: score, unit counts, control |
| `search_turn` | Same as scout payload | Returns scout lines (duplicate if called unnecessarily) |
| `search_for` | ~2,000-8,000 tokens | Variable: 1-15 result lines with full metadata |
| `deepen` | ~1,500-6,000 tokens | Extends one line; returns deepened alternatives |
| `expand_risk` | ~500-1,500 tokens | Risk payload with threats, recapture, adjusted score |
| `simulate_move` | ~300-600 tokens | Resolved state + opponent window detail |
| `simulate_line` | ~800-2,000 tokens | Multi-step line resolution |
| `get_card_detail` | ~200-400 tokens | Full card definition with abilities |
| `lookup_rule` | ~300-800 tokens | Relevant rules excerpt |
| `get_keyword` | ~50-150 tokens | Single keyword glossary entry |
| `get_opponent_history` | ~300-800 tokens | Opponent action summary |

**Heavy tools:** `search_for`, `deepen` (2K-8K tokens)  
**Light tools:** `get_keyword`, `get_card_detail` (50-400 tokens)

**Typical tool mix per decision:**
- 1× `evaluate_position` or `search_turn` (first round)
- 1-2× `search_for` or `deepen` (investigation rounds)
- 0-1× `simulate_move` or `expand_risk` (edge cases)
- 1× terminal tool (`commit_line` or `emit_goals`)

**Mean tool result tokens per decision:** ~3,000-6,000 (across 2-3 non-terminal rounds)

### 2.5 Feedback Envelopes (after search tools)

From `reasoner.py` line 1030-1050 (`build_feedback_envelope`):

```python
envelope = build_feedback_envelope(
    previous_query={"tool": name, **args},
    result_status=status,
    engine_state_delta=_resolved_delta_summary(lines),
    opponent_windows=...,
    tool_error=...,
    is_repeat=...,
    forward_progress=...,
    branch_control=...,
    revised_hypothesis=...,
)
```

**Size:** ~200-500 tokens (structured guidance after `search_for`/`deepen`)

**Frequency:** After every `search_for` or `deepen` call (1-2 per decision)

---

## 3. Current Instrumentation (Commit b637f2fd)

From `baseline_report.py` line 345-381 (`get_token_stats`):

```python
def get_token_stats(db_path: str) -> dict[str, Any]:
    """Aggregate Reasoner token spend from reasoner_decisions."""
    cur.execute("""
        SELECT
            COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
            COALESCE(SUM(model_calls), 0) AS model_calls,
            ...
        FROM reasoner_decisions
        WHERE terminal_kind IS NOT NULL
    """)
```

**Captured per turn:**
- `prompt_tokens`, `completion_tokens`, `total_tokens`
- `model_calls` (per decision)
- `reasoner_latency_ms`, `engine_latency_ms`

**Aggregation:** Total and per-turn averages in `baseline_summary.json`

**Gap:** No per-call breakdown within a decision (e.g., first call vs subsequent calls). The current instrumentation sums tokens **per decision**, not per ReAct iteration.

**What's missing for deeper profiling:**
- Per-call token split (system vs user vs tool results)
- Tool-specific result token costs
- Cached vs uncached token distinction (if caching enabled)

---

## 4. Cost Optimization Recommendations

### 4.1 Enable Prompt Caching (High Impact, Low Risk)

**Problem:** System prompt + tool schemas are **static per decision** but resent on every model call within the ReAct loop. For a 4-call decision, the same 7K-10K token prefix is sent 4 times.

**Solution:** Use OpenAI Prompt Caching (GPT-4o, GPT-4-turbo) or Claude Prompt Cache to mark the system + tools as cacheable.

**Implementation:**
- **OpenAI Prompt Caching** (Beta): Mark `system` message and tool definitions with `cache_control` (if supported)
- **Claude Prompt Cache** (Anthropic): Use `system` cache_control blocks (requires Claude 3.5+)
- **Fallback:** If OpenAI doesn't support caching on tools, restructure to prepend tools as a cached system message block

**Estimated savings:**
- **First call:** Full cost (system + tools = ~7K-10K tokens)
- **Subsequent calls (cache hit):** ~90% discount on cached prefix (~700-1K tokens billed)
- **Per decision:** 3 calls × 7K cached = **~18K token savings** (60-70% of input tokens)
- **N=20 baseline:** 400 decisions × 18K = **~7.2M tokens saved** (~$36 saved at GPT-4o input rates)

**Risks:**
- Cache expiration (OpenAI: 5-10 min TTL) may miss on long turns; monitor cache hit rate
- Adds complexity to prompt construction (requires caching-aware message ordering)
- Not all providers support caching (fallback must be no-op on non-supporting models)

**Recommendation priority:** **HIGH** — Single largest cost lever with minimal quality impact.

---

### 4.2 Reduce Scout Line Detail (Medium Impact, Low Risk)

**Problem:** Scout lines are rendered with **full detail** (`resolved_state`, score breakdowns, cluster keys, risk summaries) on the first call, even though the Reasoner often commits the scout leader without reading all metadata.

**Current payload** (line 380-459): Every line includes:
- `deepen_hint` (nested object)
- `resolved_state` (10+ keys)
- `top_score_terms` (4-item dict)
- `risk` summary (when present)

**Solution:** Send a **lean scout payload** on the first call (line IDs + moves + scores only), then provide full detail via:
1. A **lazy `get_line_detail(line_id)`** tool (returns full metadata on demand)
2. Automatically append detail for the **top 3 lines** only (rest stay lean)

**Estimated savings:**
- **Current:** 10 lines × 400 tokens = 4,000 tokens
- **Lean:** 10 lines × 150 tokens (ID + moves + score) = 1,500 tokens
- **Per decision:** ~2,500 tokens saved (20-30% of first-call input)
- **N=20 baseline:** 400 decisions × 2,500 = **~1M tokens saved** (~$5)

**Risks:**
- Requires tool call to access metadata (adds 1 round for detail-heavy decisions)
- May increase model calls if detail is needed but not in top 3
- Net savings only if detail is rarely accessed (<50% of decisions)

**Recommendation priority:** **MEDIUM** — Moderate savings; worth testing if caching isn't enough.

---

### 4.3 Tighten ReAct Loop Budget (Medium Impact, Medium Risk)

**Problem:** `REASONER_MAX_TOOL_ROUNDS = 6` allows up to 6 model calls before fallback. Many decisions commit in 2-3 rounds; the extra headroom is rarely used but still adds latency risk.

**Current distribution** (estimated from acceptance tests):
- 40-60% commit in 2-3 rounds
- 30-40% commit in 3-5 rounds
- 5-10% exhaust budget and fallback

**Solution:** Reduce to `REASONER_MAX_TOOL_ROUNDS = 4` (down from 6).

**Estimated impact:**
- **Unchanged:** 80-90% of decisions (already commit in ≤4 rounds)
- **Forced earlier commit:** 5-10% (would have used rounds 5-6 for redundant investigation)
- **Forced fallback:** 1-3% (would have committed in round 5-6; now fallback)

**Estimated savings:**
- **Per affected decision:** 2 rounds × 10K tokens/call = ~20K tokens saved
- **Frequency:** ~5-10% of decisions → 20-40 decisions in N=20
- **N=20 baseline:** 30 decisions × 20K = **~600K tokens saved** (~$3)

**Risks:**
- Increases fallback rate by 1-3% (small degradation in commit rate)
- May truncate useful investigation for complex positions
- Latency savings (~2-4s p95 reduction) may not matter if turn time budget is comfortable

**Recommendation priority:** **MEDIUM** — Modest savings with minor quality risk. Test on a pilot run first.

---

### 4.4 Remove Redundant `search_turn` Calls (Low Impact, Low Risk)

**Problem:** From line 712-713 comment:

```python
"SCOUT BASELINE (already grounded; do not call search_turn merely to reread it):\n"
```

The scout baseline is **already in the user message**, but the model sometimes calls `search_turn` on the first round (returns duplicate data).

**Solution:**
1. Add `search_turn` to a **first-round block list** (force `evaluate_position` or a search tool instead)
2. Update the prompt to emphasize "scout baseline is below; call search_turn only if you need a refreshed corpus"

**Estimated savings:**
- **Frequency:** 10-20% of decisions (when model calls `search_turn` first)
- **Per occurrence:** ~4K tokens (duplicate scout payload)
- **N=20 baseline:** 60 decisions × 4K = **~240K tokens saved** (~$1.20)

**Risks:**
- Model may need `search_turn` to refresh corpus mid-turn (edge case)
- Easy to revert if it causes confusion

**Recommendation priority:** **LOW** — Small savings; nice-to-have polish.

---

### 4.5 Use Cheaper Model for Routine Decisions (Medium Impact, High Risk)

**Problem:** GPT-4o (or GPT-4-turbo) is expensive ($5 input / $15 output per 1M tokens). Routine decisions (commit scout leader, single-legal-move) may not need flagship intelligence.

**Solution:** Route simple decisions to **GPT-4o-mini** ($0.15 input / $0.60 output per 1M tokens) or similar budget model.

**Heuristic for "simple decision":**
- Scout agreement (commit leader without investigation)
- Single complete legal line
- Exemption applied (forced, budget exhausted)

**Estimated savings:**
- **Frequency:** 40-50% of decisions (scout agreement)
- **Per decision:** 40K tokens × ($5 - $0.15)/1M = ~$0.19 saved
- **N=20 baseline:** 180 decisions × $0.19 = **~$34 saved**

**Risks:**
- **Quality degradation:** Cheaper model may make worse decisions even on "simple" cases
- **Commit rate drop:** Mini model may fail terminal validation more often
- **Baseline divergence:** Using two models makes baseline non-reproducible
- **Complexity:** Requires router logic to classify "simple" decisions upfront

**Recommendation priority:** **LOW for baseline** — High risk of polluting baseline metrics. Consider only **after** baseline is archived and SPRT self-play testing is set up.

---

### 4.6 Increase SEARCH Fallback Use (Low Impact, Unknown Risk)

**Problem:** The Reasoner is a **live decision-maker** on top of SEARCH (argmax base selector). Falling back to SEARCH is cheap (no Reasoner LLM calls), but requires SEARCH to be reliable.

**Solution:** Expand exemptions (single-legal-move, forced, low-complexity heuristics) to skip Reasoner more often and use SEARCH argmax.

**Estimated savings:**
- **Frequency:** Variable (depends on exemption tuning)
- **Per skipped decision:** ~$0.22 saved (full Reasoner cost)
- **N=20 baseline:** 50 extra exemptions × $0.22 = **~$11 saved**

**Risks:**
- **Commit rate denominator shrinks** (fewer eligible Reasoner turns)
- **Baseline loses signal** if too many turns are exempt
- **Quality unclear:** SEARCH argmax may be worse than Reasoner for non-trivial decisions

**Recommendation priority:** **LOW for baseline** — Baseline should measure Reasoner **reliability**, not SEARCH coverage. Defer to post-baseline optimization.

---

### 4.7 Consider Responses API Migration (Unknown Impact, High Effort)

**Context:** From task description: "a separate planned migration from Chat Completions to the Responses API."

**Current API:** `chat.completions.create` (Chat Completions)  
**Alternative:** Responses API (if this refers to a provider-specific feature like Anthropic's Messages API or a hypothetical OpenAI Responses endpoint)

**Analysis gap:** Without details on the Responses API's token accounting, tool-call format, or caching behavior, I cannot estimate cost impact.

**Recommendation:** Defer Responses API migration **until after baseline**. Baseline should use the current Chat Completions API for reproducibility. Profile the migration separately.

---

## 5. Prioritized Action Plan

### Phase 1: Baseline with Current Architecture (Do First)
1. **Run N=3 pilot** with current code (commit b637f2fd) to validate token instrumentation
2. **Archive token breakdown** (prompt vs completion, per-turn avg, p95)
3. **Measure actual cache behavior** if provider already caches (log cache hit/miss if exposed)
4. **Identify outlier decisions** (>100K tokens) and log their characteristics

### Phase 2: Low-Hanging Fruit (Do Immediately After Pilot)
1. **Enable prompt caching** (if provider supports): 50-75% input savings
2. **Remove redundant `search_turn` calls** (block-list first round): ~5-10% savings
3. **Re-run N=3 pilot** with caching + search_turn fix; compare costs

### Phase 3: Medium-Effort Optimizations (Do After Baseline)
1. **Test lean scout payload** (lazy detail tool): A/B test on N=10
2. **Test REASONER_MAX_TOOL_ROUNDS = 4**: Measure commit rate impact
3. **Archive separate baseline** for each change (caching, lean scout, tight loop) to measure quality vs cost tradeoffs

### Phase 4: Defer Until SPRT Testing (Post-Baseline)
1. **Cheaper model routing** (GPT-4o-mini for simple decisions): SPRT win-rate gate required
2. **Expand SEARCH exemptions**: Requires separate baseline for SEARCH-only performance
3. **Responses API migration**: Separate task; measure cost/quality independently

---

## 6. Measurement Recommendations

### 6.1 Per-Decision Token Breakdown
Extend `_record_token_usage` to log:
- First-call input tokens (system + tools + context + scout)
- Subsequent-call input tokens (system + tools + tool result)
- Per-tool result token size (log on tool return)
- Cached vs uncached token split (if provider exposes)

**Storage:** Add columns to `reasoner_decisions`:
- `first_call_input_tokens`, `subsequent_call_input_tokens`
- `tool_result_tokens_json` (array of per-tool sizes)
- `cache_hit_count`, `cache_miss_count` (if available)

### 6.2 Cost Per Game
Aggregate token totals per game:
- Total input tokens (all decisions)
- Total output tokens
- Total estimated cost ($)

**Output:** `baseline_summary.json` add:
```json
{
  "total_input_tokens": 16000000,
  "total_output_tokens": 480000,
  "estimated_cost_usd": 88.20,
  "mean_input_tokens_per_decision": 40000,
  "p95_input_tokens_per_decision": 75000
}
```

### 6.3 Tool Usage Frequency
Already captured in `get_tool_usage` (line 260-292). Extend to track:
- `search_for` vs `deepen` split
- `search_turn` called on first round (flag redundancy)
- Heavy tool result sizes (>5K tokens)

---

## 7. Conclusion

**Feasibility of N=20 baseline:** Approximately **$88** at current architecture (GPT-4o, no caching). This is **affordable for a one-time baseline** but expensive for routine testing.

**Top priority:** **Enable prompt caching immediately** — this single change reduces cost to **~$20-30** (65-75% savings) with zero quality impact.

**After caching:** N=20 becomes **cheap enough for weekly regression runs**. Further optimizations (lean scout, tight loop) are nice-to-haves for N=50+ or continuous testing.

**Baseline recommendation:**
1. Run N=3 pilot with **current code + caching enabled** to validate instrumentation
2. Run N=20 baseline with caching to archive a **caching-enabled baseline** (not a legacy no-caching baseline, since caching is free savings)
3. Measure actual costs and compare to this report's estimates
4. Archive token breakdowns and cost per game in `baseline_summary.json`
5. Defer lean scout / tight loop to **post-baseline optimization** (separate PRs with A/B testing)

---

## Appendix A: Static Token Estimates (Methodology)

**Character-to-token conversion:** ~3.5 characters/token (English prose average)  
**JSON overhead:** ~1.2× multiplier for structured data (keys, quotes, commas)  
**Validation:** Spot-checked against OpenAI tokenizer for key prompt modules (±10% accuracy)

**Tool schema estimate:** Counted `TOOLS` array size (14,722 chars) → 14,722 / 3.5 × 1.2 ≈ **5,000 tokens** (adjusted to ~3,500-4,200 based on tool definitions being terse)

**Scout line estimate:** Measured `_render_scout_lines` output for a sample 10-line payload from test fixtures → ~4,200 tokens (JSON indent=2)

**Disclaimer:** Estimates are ±20% until measured on live baseline data. Pilot run will refine.

---

## Appendix B: References

- `ai_agent/reasoner.py`: ReAct loop, tool schemas, token telemetry
- `ai_agent/baseline_report.py`: Token aggregation, commit b637f2fd instrumentation
- `ai_agent/docs/Reasoner_Multi_Game_Baseline_Plan.md`: Baseline plan, cost context
- `ai_agent/prompts/`: System prompt modules (role, discipline, few-shot)
- `ai_agent/agent.py`: TOOLS array definition (14 tools × ~250-300 tokens)

---

**Report author:** Cursor Cloud Agent  
**Review status:** Draft (pending Bryan review)  
**Next steps:** Run N=3 pilot with caching enabled, then finalize recommendations.
