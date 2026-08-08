# Eval Report — `reasoner-live-smoke`

Live Reasoner decision-quality smoke (agent lane only). Requires Godot + LLM credentials.

- Mode: `engine_backed`
- Repeats: 1
- Transforms: identity
- Trials: 7

## Profile summary

| Profile | Trials | Passed | Errors | Mean score |
|---|---:|---:|---:|---:|
| `reasoner-default` | 7 | 6 | 0 | 0.964 |

## Failures

- `gust-might-filter` / `reasoner-default` (transform=identity, rep=0): gold:{'checks': [{'kind': 'gust_valid_target', 'passed': False, 'description': 'Valid might-filtered target'}]}

## Notes

- Hard validity, gold decision quality, cost, and strength are reported separately.
- Silver search agreement is diagnostic and never the sole release gate.
- Free-form rationale text is excluded from trajectory gates.
- `engine_backed` manifests exercise Godot + real adapters; `agent_only` stays mock-safe for CI.
