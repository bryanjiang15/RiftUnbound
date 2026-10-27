# Token Profiling for Reasoner Optimization

How to measure and analyze token usage in the Reasoner's LLM calls to identify cost-reduction opportunities.

## Overview

The Reasoner is a ReAct-style loop that makes multiple LLM calls per decision, accumulating context (system prompt, game state, assistant history, and tool results) on each step. This instrumentation tracks:

- Token composition per call: system message, state, scout baseline, assistant history, tool results, envelopes/nudges, and residual
- Actual API token counts and caching statistics
- Cost breakdown and growth patterns

## Usage

### 1. Run a Reasoner self-play game with token profiling

Token profiling is **always on** in `reasoner.py`. Run the Reasoner baseline flow to generate profiled games:

```bash
# Start engine server (in Godot project)
export RIFTBOUND_SEARCH=on
export RIFTBOUND_ENGINE_SERVER=on
export RIFTBOUND_ENGINE_PORT=8770
export RIFTBOUND_LOG_INPUTS=1

# Start Reasoner agent (in separate terminal)
export OPENAI_API_KEY=sk-...
export RIFTBOUND_REASONER=on
export RIFTBOUND_ENGINE_PORT=8770
export RIFTBOUND_LOG_INPUTS=1
uvicorn ai_agent.main:app --port 8765

# Run self-play games (from repo root, with Godot in PATH)
./Scripts/run_reasoner_baseline.sh --games 2 --seed 5000
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
- **Prompt composition share**: Breakdown of system, state, scout, assistant_hist, tools, envelope, other
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

Uncached input dominates the bill when caching is high — e.g., with 59% caching, uncached tokens are still ~78% of cost.

## Static Analysis: What Grows Per Step

Evidence from profiled games shows these sources of prompt growth:

### Step 0 (initial)
- System prompt (~1.2K tokens, flat)
- State + scout baseline (~800 + variable tokens, flat)
- Total: ~2-3K tokens

### Steps 1-N (tool rounds)
Each tool round adds:
- **Assistant tool-call turn** (~50-150 tokens): the model's `tool_calls` message listing which tools to invoke
- **Tool results** (variable, largest contributor):
  - `deepen` can be ~52K tokens per result (pre-compaction)
  - `search_for` typically ~3-5K tokens
  - Other tools (get_card_detail, lookup_rule): <500 tokens each
- **Feedback envelopes** (~200-400 tokens): the investigation_metrics advisory sent back to the model after search tools

### Growth trajectory
A typical 4-step decision with 2 deepen calls:
- Step 0: ~2.6K tokens
- Step 1 (search_for): ~2.6K + 3K tool + 0.4K envelope = ~6K total
- Step 2 (deepen): ~6K + 52K tool + 0.4K envelope = ~58K total
- Step 3 (deepen): ~58K + 52K tool + 0.4K envelope = ~110K total
- Step 4 (commit_line): ~110K + 0.2K rejection + nudge = ~110K total

**Key insight:** Tool results (especially `deepen`) and their re-transmission dominate growth. System/state/assistant history are small by comparison.

## What the "other" Bucket Captures

The `other` field in the report is a residual: actual prompt tokens minus the sum of estimated parts (system + state + scout + assistant_hist + tools + envelope). Sources:

- Formatting overhead (JSON encoding, role markers, tool_call metadata)
- Small user nudges ("Do not end in prose. Call commit_line...")
- Estimation error (tiktoken approximation vs OpenAI's real tokenizer)

A healthy `other` value is 5-15% of the prompt. If `other` is negative or >20%, the estimator may be missing a source.
