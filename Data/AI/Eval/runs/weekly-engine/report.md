# Eval Report — `weekly-engine`

Weekly engine-contract suite (Godot argmax, metamorphic transforms, no LLM).

- Mode: `engine_backed`
- Repeats: 1
- Transforms: identity, reorder_hand, reorder_base_units, swap_battlefield_ids
- Trials: 44

## Profile summary

| Profile | Trials | Passed | Errors | Mean score |
|---|---:|---:|---:|---:|
| `baseline-argmax` | 44 | 44 | 0 | 1.000 |

## Failures

None.

## Notes

- Hard validity, gold decision quality, cost, and strength are reported separately.
- Silver search agreement is diagnostic and never the sole release gate.
- Free-form rationale text is excluded from trajectory gates.
- `engine_backed` manifests exercise Godot + real adapters; `agent_only` stays mock-safe for CI.
