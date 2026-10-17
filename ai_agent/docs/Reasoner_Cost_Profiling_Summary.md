# Reasoner Cost Profiling — Quick Reference

**Date:** 2026-10-17  
**Full report:** `Reasoner_Cost_Profiling_Report.md`

## Key Findings

### Current Cost (per decision)
- **~40K input tokens** (mean), ~1.2K output tokens
- **~$0.22 per decision** (GPT-4o rates)
- **N=20 baseline: ~$88** (400 decisions × $0.22)

### Cost Drivers (by token volume)
1. **System prompt** (4K-8K tokens/call) — role + rules + few-shot examples
2. **Tool schemas** (3K-4K tokens/call) — 14 tool definitions
3. **Scout lines** (2K-10K tokens/call) — variable, depends on line count and detail
4. **Tool results** (3K-6K total/decision) — `search_for` and `deepen` are heavy
5. **ReAct loop overhead** — 3-5 model calls per decision on average

### Top 3 Recommendations

| Recommendation | Savings | Risk | Priority |
|----------------|---------|------|----------|
| **1. Enable prompt caching** | 50-75% input tokens (~$36 on N=20) | Low | **HIGH** |
| **2. Reduce scout line detail** | 20-30% first-call input (~$5 on N=20) | Low-Med | **MEDIUM** |
| **3. Tighten ReAct loop budget** (6→4 rounds) | 15-25% total cost (~$3 on N=20) | Medium | **MEDIUM** |

### Immediate Action
**Enable prompt caching** before N=20 baseline:
- Mark system prompt + tool schemas as cacheable
- Expected cost: **$20-30** (down from $88)
- Zero quality impact — pure savings

### Baseline Recommendation
1. Run N=3 pilot with **caching enabled** to validate savings
2. Run N=20 baseline with caching (target: ~$25-30)
3. Archive actual token/cost data in `baseline_summary.json`
4. Defer further optimizations to post-baseline PRs

---

## Token Breakdown (per decision, estimated)

| Phase | Input tokens | Output tokens |
|-------|-------------|---------------|
| First call (context + scout) | 10K-25K | 200-400 |
| Tool round 1 (result) | 7K-12K | 200-400 |
| Tool round 2 (result) | 7K-12K | 200-400 |
| Terminal call | 7K-10K | 100-200 |
| **Total (3-4 calls)** | **31K-59K** | **700-1,400** |

**With caching (system + tools cached):**
- First call: 10K-25K (cache miss)
- Subsequent: 3K-5K each (cache hit, ~90% discount on cached prefix)
- **Total (3-4 calls): 16K-40K input** (~40-50% savings)

---

## Measured Gaps (post-baseline)
Current instrumentation (commit b637f2fd) tracks **per-decision totals** but lacks:
- Per-call breakdown (first vs subsequent)
- Tool result token sizes
- Cache hit/miss rates
- Prompt component attribution

Extend telemetry in post-baseline optimization work.
