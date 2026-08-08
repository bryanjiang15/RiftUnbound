# Eval Report — `blocking-smoke`

Offline plumbing smoke across all blocking cases (mock adapter). Not a quality gate.

- Mode: `agent_only`
- Repeats: 1
- Transforms: identity
- Trials: 12

## Profile summary

| Profile | Trials | Passed | Errors | Mean score |
|---|---:|---:|---:|---:|
| `baseline-argmax-mock` | 12 | 12 | 0 | 1.000 |

## Failures

None.

## Notes

- Hard validity, gold decision quality, cost, and strength are reported separately.
- Silver search agreement is diagnostic and never the sole release gate.
- Free-form rationale text is excluded from trajectory gates.
- `engine_backed` manifests exercise Godot + real adapters; `agent_only` stays mock-safe for CI.
