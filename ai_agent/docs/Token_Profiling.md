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
