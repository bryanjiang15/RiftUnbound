# Eval Report — `decision-v2-overcommit-smoke`

Single-case argmax smoke for refuse-overcommit-contested-bf

- Mode: `engine_backed`
- Repeats: 1
- Transforms: identity
- Trials: 1

## Profile summary

| Profile | Trials | Passed | Errors | Mean score |
|---|---:|---:|---:|---:|
| `baseline-argmax` | 1 | 0 | 0 | 0.750 |

## Metrics

| Profile | Hard gold | Easy gold | Trap rate | Validity fail | Timeout | p95 latency ms | Mean tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| `baseline-argmax` | 0.0% (0/1) | n/a | 100.0% (1/1) | 0.0% | 0.0% | 1595 | 0 |

## Failures

- `refuse-overcommit-contested-bf` / `baseline-argmax` (transform=identity, rep=0): gold:{'trap_hit': True, 'traps': [{'kind': 'line_contains', 'passed': True, 'description': 'Overcommit into contested A (buff/move/reinforce) into opponent wipe range'}], 'checks': []}

## Notes

- Hard validity, gold decision quality, cost, and strength are reported separately.
- Silver search agreement is diagnostic and never the sole release gate.
- Free-form rationale text is excluded from trajectory gates.
- `engine_backed` manifests exercise Godot + real adapters; `agent_only` stays mock-safe for CI.
- See `metrics.json` for full numeric aggregates (hard/easy gold, trap rate, latency, tokens).
