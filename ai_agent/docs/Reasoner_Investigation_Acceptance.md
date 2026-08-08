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

## Related docs

- `Reasoner_Investigation_Improvements.md` §5.3
- `AI_Evaluation_Operations.md`
- `Deliberative_Reasoning_Toolkit.md` Phase 4
