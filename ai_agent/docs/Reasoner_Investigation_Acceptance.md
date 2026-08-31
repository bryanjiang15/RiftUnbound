# Reasoner Investigation Acceptance Notes

Status: **plumbing + controller/prompt redesign landed**; live LLM A/B and SPRT
still require Godot + credentials in the operator environment.

## What shipped

| Phase | Capability |
|---|---|
| 1 | Investigation telemetry flattened into eval `metrics.json`; `investigate-baseline` / `investigate-report` CLI |
| 2 | Investigator prompts, few-shot traces, scout `resolved_state`, soft score bands |
| 3 | `deepen(..., prefix_steps=k)`, typed `result_status`, illegal-seed repair hints |
| 4 | Novelty gate, OR’d `comparison_required`, per-round feedback envelope, score-only rejection, rule-based advisory critic |
| 5 | Profile `reasoner-investigate-v2` + manifest `reasoner-investigate-accept.json` |
| 6 | Bernoulli SPRT helpers + `python -m ai_agent.eval sprt-report` |

## Commands

```bash
# Unit / offline
python -m pytest ai_agent/tests/ -q
python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/blocking.json

# Archive or refresh investigation baseline report
python -m ai_agent.eval investigate-baseline
python -m ai_agent.eval investigate-report --run-dir Data/AI/Eval/runs/reasoner-live-smoke

# Live A/B (Godot + LLM)
export GODOT=...
python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/reasoner-investigate-accept.json

# SPRT from arena pair JSONL
python -m ai_agent.eval sprt-report --pairs-jsonl /path/pairs.jsonl --out Data/AI/Eval/runs/sprt/report.md
```

## Acceptance thresholds (tune after live baseline)

- ≥90% eligible turns: successful *novel* `search_for` / `deepen` (or documented exemption)
- 100% commits: complete, root-matched registry lines
- Material drop in score-only rationales vs Phase 1 baseline
- No hard-gold / trap regression beyond agreed noise on decision-v2
- SPRT `accept_h1` vs frozen baseline before flipping default profile

## Live investigation contracts

These are the invariants the Reasoner acceptance run is meant to protect. They
come from `reasoner.py`, `skills.deepen`, `TurnSearch.gd`, and the regression
tests listed below.

### Commit surface

`commit_line` may only name a line that is already in the request-scoped
registry. The line must be:

- legal and `complete`
- searched from the pinned `root_state_hash`
- executable as parallel arrays: `moves`, `move_contexts`, and
  `expected_pre_hashes` with one non-empty pre-step hash per command

Godot replays those hashes before each command. If the opponent acts or the live
state diverges, `AIPlayer.gd` drops the committed line and replans from the new
state instead of replaying stale commands.

### Deepening from a pivot

Use `deepen(line_id=..., prefix_steps=k)` to fork an existing scout line at a
strategic pivot. `prefix_steps` keeps only the first `k` commands from the
registered line, then strips a trailing `end turn` so `TurnSearch` can expand
from the tip. A `prefix_steps` value of zero, or a prefix that leaves no command
after trailing `end turn` stripping, is rejected.

Seed replay has a subtle rule: between explicit seed commands, `TurnSearch`
settles only opponent windows and opponent prompts. It stops whenever the AI
seat must act, so stored intermediate AI `pass` / `choose` commands replay as
their own line steps and are not double-applied by full quiescence. After the
whole seed prefix is applied, normal quiescence resumes before beam expansion.
If a seed fails, the tool returns `result_status: "illegal_seed"` with a shorter
prefix suggestion when available.

Prefer a 1-3 strategic-action prefix ending at the pivot. Do not hand-author
engine-generated `choose` or `pass` steps in a manual `moves` prefix; use
`line_id` + `prefix_steps` when the seed needs those stored intermediates.

### Tool feedback ordering

The Reasoner may issue multiple tools in one assistant turn, including parallel
`deepen` calls. OpenAI's tool protocol requires all tool replies to appear
immediately after that assistant `tool_calls` message. The feedback envelopes
(`supported` / `contradicted` / `not tested`, concrete state facts, next
uncertainty) are therefore appended only after every tool reply for that turn.

## Related docs

- `Reasoner_Investigation_Improvements.md` §5.3
- `AI_Evaluation_Operations.md`
- `Deliberative_Reasoning_Toolkit.md` Phase 4
- `Phase2_5_Engine_Truth_Simulation.md` §5-8

## Contract tests

```bash
python -m pytest \
  ai_agent/tests/test_deepen_prefix_steps.py \
  ai_agent/tests/test_reasoner_loop.py \
  ai_agent/tests/test_reasoner_terminals.py -q

# Godot-backed contract checks, when a Godot binary is available:
./Scripts/run_tcg_tests.sh RuleSearch RuleReasoner
```
