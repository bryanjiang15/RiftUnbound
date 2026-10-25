# Token Profiling for Reasoner Optimization

How to measure and analyze token usage in the Reasoner's LLM calls to identify cost-reduction opportunities.

## Overview

The Reasoner is a ReAct-style loop that makes multiple LLM calls per decision, accumulating context (system prompt, game state, assistant history, and tool results) on each step. This instrumentation tracks:

- Token composition per call: system message, state, assistant history, and tool results
- Actual API token counts and caching statistics
- Cost breakdown and growth patterns

## Usage

### 1. Run a game with token profiling enabled

Token profiling is **always on** in `reasoner.py`. Run any evaluation or self-play game:

```bash
# Example: run a single self-play game
python -m ai_agent.main --seed 5000 --player1 reasoner --player2 reasoner

# Or run an eval position
python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/blocking.json
```

The Reasoner logs token profiles to `ai_agent/agent_search.log`.

### 2. Generate the token profile report

```bash
# Text report to stdout
python -m ai_agent.tools.token_profile

# Markdown report
python -m ai_agent.tools.token_profile --markdown > token_report.md

# Custom log path
python -m ai_agent.tools.token_profile path/to/agent_search.log
```

### 3. Interpret the report

The report shows:

- **Total tokens and cost**: Prompt (uncached + cached), completion, estimated dollars
- **Average prompt size by step**: Shows growth within decisions (step 0, 1, 2, ...)
- **Prompt composition share**: Breakdown of system, state, assistant_hist, and tool results
- **Tool result tokens**: Total tokens per tool (search_for, deepen, etc.)
- **Top 10 largest tool results**: Identifies the heaviest individual tool outputs
- **Trivial decisions**: Decisions that ended in 1-2 steps (forced moves, single legal action)
- **Cached token share per step**: Shows how caching improves over the loop

## Example Workflow

```bash
# Clear old logs
rm ai_agent/agent_search.log

# Run one game
python -m ai_agent.main --seed 5000 --player1 reasoner --player2 reasoner

# Generate markdown report
python -m ai_agent.tools.token_profile --markdown > logs/token_profile_seed5000.md

# Review findings
cat logs/token_profile_seed5000.md
```

## Interpretation Notes

### Prompt growth by step

If `avg_prompt_by_step` shows steep growth (e.g., step 0: 2K tokens, step 3: 10K tokens), the Reasoner is accumulating history. Investigate:

- Are all assistant messages necessary?
- Can tool results be summarized or truncated?
- Are stale observations being re-sent?

### Tool result breakdown

If a single tool dominates the token budget (e.g., `search_for: 50,000 tokens` in a 56-call game), check:

- Can the tool's JSON output be pruned (remove verbose or unused fields)?
- Is the tool being called redundantly?
- Can the tool return a compact summary instead of full data?

### Trivial decisions

If a significant portion of cost comes from trivial decisions (forced moves), consider:

- Short-circuit the Reasoner for single-legal-action states
- Cache trivial decision outcomes
- Use a cheaper model for trivial cases

### Cached token share

High caching (>50%) is good but not sufficient — uncached tokens still dominate cost when the prompt is large. Focus on reducing the **total prompt size** first.

## Cost Model

Default pricing (per 1M tokens):

- Input: $2.50
- Cached input: $0.25
- Output: $15.00

Uncached input is ~78% of the bill when caching is 59% (context from PR description).

## Static Analysis Findings

See the PR description for a code-level analysis of what grows per step and what could be trimmed.

## Token Compaction Feature

Starting with the compact tools PR, the Reasoner includes an optional **token compaction** mode that reduces prompt size by:

1. **Compact deepen output**: Returns a summary per line (best moves, scores, key state deltas) instead of the full payload, with a hard size cap (~1500 tokens).
2. **Stub old tool results**: Once a tool result has been sent, subsequent prompts replace it with a short stub that notes what it was. Only the latest tool result of each type stays full.

### Configuration

The compaction is controlled by the `RIFTBOUND_REASONER_COMPACT_TOOLS` environment variable:

- **Default**: ON (`1`)
- **Disable**: Set to `0`, `false`, `off`, or `no`

```bash
# Run with compaction enabled (default)
python -m ai_agent.main --seed 5000 --player1 reasoner --player2 reasoner

# Disable compaction to compare
RIFTBOUND_REASONER_COMPACT_TOOLS=0 python -m ai_agent.main --seed 5000 --player1 reasoner --player2 reasoner
```

### Comparison Tool

To measure the actual token savings, use `compare_trims.py`:

```bash
# Dry-run to see which scenarios would be tested
python -m ai_agent.tools.compare_trims --dry-run

# Run comparison (requires OPENAI_API_KEY)
python -m ai_agent.tools.compare_trims

# Run with 3 repeats per scenario for noise reduction
python -m ai_agent.tools.compare_trims --repeat 3

# Test with a different model
python -m ai_agent.tools.compare_trims --model gpt-5.6-sol-medium
```

The comparison tool:

- Loads a fixed set of mid/late-game scenarios from the eval corpus (or synthetic examples if corpus is unavailable)
- Runs each scenario with `RIFTBOUND_REASONER_COMPACT_TOOLS=0` (off) and `=1` (on)
- Reports per-scenario and aggregate:
  - Prompt, cached, and completion token counts
  - Estimated cost in USD
  - Number of Reasoner steps
  - Chosen action and whether both runs agree
- Supports `--repeat N` to reduce noise from model non-determinism

### Reading Comparison Results

The report includes:

- **Aggregate totals**: Total tokens and cost across all runs, off vs on
- **Savings**: Absolute and percentage reduction in prompt tokens and cost
- **Agreement rate**: How often the compact and full modes chose the same line (should be high; significant divergence suggests information loss)
- **Per-scenario breakdown**: Shows token counts, steps, cost, and agreement for each test case

Example output:

```
Aggregate Totals:
  Compact OFF: 1,032,450 prompt, 610,000 cached, 8,200 completion, $5.23
  Compact ON:  578,120 prompt, 340,000 cached, 8,100 completion, $2.47

  Prompt token savings: 454,330 (44.0%)
  Cost savings: $2.76 (52.8%)

Agreement on chosen line: 11/12 (91.7%)
```

### What the Compaction Preserves

The compact deepen and stub logic preserve all fields required for commit validation:

- `line_id`, `expected_pre_hashes`, `root_state_hash`
- `complete`, `terminal_reason`
- Scores and risk-adjusted scores (if present)
- Core state deltas (wins_game, my_score_after, opp_score_after, next_decision)

The compaction drops:

- Full move contexts beyond the first 6 moves per line
- Verbose resolved_state fields (units_killed, cards_drawn, etc.)
- Lines beyond the top 10
- Old tool results (replaced with stubs after first use)

### Risks and Caveats

- **Information loss**: The compact form may drop context the model could have used. Monitor the agreement rate; if it drops below ~85%, the compaction may be too aggressive.
- **Commit failures**: If HASH_DIVERGE or validation errors increase, the compaction may have removed a required field. File a bug with the scenario.
- **Model dependence**: Some models (especially non-OpenAI) may be more sensitive to the compaction. Test before deploying in production.
- **Caching interaction**: Compaction changes the prompt structure, which may reduce caching effectiveness on the first turn after enabling. This is a transient effect.

### Measuring Real Savings

The profiler evidence from seed-5000 shows:

- Tool results: 55.9% of prompt tokens
- `deepen` alone: 577K of ~1.03M prompt tokens
- A single deepen was ~52K tokens and re-sent on steps 2, 3, 4

Expected savings with compaction:

- Deepen compaction (~1.5K cap): ~95% reduction per deepen result
- Stub replacement: ~99% reduction on re-sent results (keeps ~100-200 token stub)

Realistic aggregate savings depend on the decision mix (how many deepen calls, how many steps). Use `compare_trims.py` on your own scenarios to measure.
