extends RefCounted
class_name CombatOutcome

## Carries the result of one round of combat into the ROUND_RESULT phase.
##
## Populated by RunController._resolve_combat() (Phase D+).
## RunRoundDamage reads enemy_survivor_count when use_flat_damage is false.
var player_won_round: bool = true

## Alive opponent units at combat end. Used by RunRoundDamage (survivor-scaled damage).
var enemy_survivor_count: int = 0
## Alive player units at combat end.
var player_survivor_count: int = 0
## Full combat result including the event log. Null when using the stub fallback.
var combat_result: CombatResult = null
