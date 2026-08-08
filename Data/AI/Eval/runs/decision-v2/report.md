# Eval Report — `decision-v2`

Contested decision-v2 agent catalog (traps + hard gold). Default baseline-argmax; swap profiles to reasoner-default for live LLM.

- Mode: `engine_backed`
- Repeats: 1
- Transforms: identity
- Trials: 14

## Profile summary

| Profile | Trials | Passed | Errors | Mean score |
|---|---:|---:|---:|---:|
| `baseline-argmax` | 7 | 4 | 0 | 0.893 |
| `reasoner-default` | 7 | 4 | 0 | 0.893 |

## Metrics

| Profile | Hard gold | Easy gold | Trap rate | Validity fail | Timeout | p95 latency ms | Mean tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| `baseline-argmax` | 57.1% (4/7) | n/a | 42.9% (3/7) | 0.0% | 0.0% | 1973 | 0 |
| `reasoner-default` | 57.1% (4/7) | n/a | 42.9% (3/7) | 0.0% | 0.0% | 182882 | 42519 |

## Failures

- `float-react-energy` / `baseline-argmax` (transform=identity, rep=0): gold:{'trap_hit': True, 'traps': [{'kind': 'command_prefix', 'passed': True, 'description': 'Tap out on a non-lethal 2-drop'}], 'checks': []}
- `tempo-hold-contested-wipe` / `baseline-argmax` (transform=identity, rep=0): gold:{'trap_hit': True, 'traps': [{'kind': 'line_contains', 'passed': True, 'description': 'Overcommit into contested A (buff/move/reinforce) into opponent wipe range'}], 'checks': []}
- `tempo-hold-open-rune-reaction` / `baseline-argmax` (transform=identity, rep=0): gold:{'trap_hit': True, 'traps': [{'kind': 'line_contains', 'passed': True, 'description': 'Fragile 2-might conquer into open Gust (bounce)'}], 'checks': []}
- `float-react-energy` / `reasoner-default` (transform=identity, rep=0): gold:{'trap_hit': True, 'traps': [{'kind': 'command_prefix', 'passed': True, 'description': 'Tap out on a non-lethal 2-drop'}], 'checks': []}
- `tempo-hold-contested-wipe` / `reasoner-default` (transform=identity, rep=0): gold:{'trap_hit': True, 'traps': [{'kind': 'line_contains', 'passed': True, 'description': 'Overcommit into contested A (buff/move/reinforce) into opponent wipe range'}], 'checks': []}
- `tempo-hold-open-rune-reaction` / `reasoner-default` (transform=identity, rep=0): gold:{'trap_hit': True, 'traps': [{'kind': 'line_contains', 'passed': True, 'description': 'Fragile 2-might conquer into open Gust (bounce)'}], 'checks': []}

## Notes

- Hard validity, gold decision quality, cost, and strength are reported separately.
- Silver search agreement is diagnostic and never the sole release gate.
- Free-form rationale text is excluded from trajectory gates.
- `engine_backed` manifests exercise Godot + real adapters; `agent_only` stays mock-safe for CI.
- See `metrics.json` for full numeric aggregates (hard/easy gold, trap rate, latency, tokens).
