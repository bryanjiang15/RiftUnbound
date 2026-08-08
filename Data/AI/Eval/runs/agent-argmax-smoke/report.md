# Eval Report — `agent-argmax-smoke`

Agent-lane decision positions under Godot TurnSearch argmax (no LLM). Baseline for decision gold labels.

- Mode: `engine_backed`
- Repeats: 1
- Transforms: identity
- Trials: 7

## Profile summary

| Profile | Trials | Passed | Errors | Mean score |
|---|---:|---:|---:|---:|
| `baseline-argmax` | 7 | 7 | 0 | 1.000 |

## Failures

None.

## Notes

- Hard validity, gold decision quality, cost, and strength are reported separately.
- Silver search agreement is diagnostic and never the sole release gate.
- Free-form rationale text is excluded from trajectory gates.
- `engine_backed` manifests exercise Godot + real adapters; `agent_only` stays mock-safe for CI.
