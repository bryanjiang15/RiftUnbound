extends RefCounted
class_name CombatOutcome

## Carries the result of one round of combat into the ROUND_RESULT phase.
##
## Produced by RunController.stub_resolve_combat() until Phase D replaces it with
## real combat resolution. RunRoundDamage reads this to calculate player health loss.
var player_won_round: bool = true

## Used by RunRoundDamage when use_flat_damage is false.
var enemy_survivor_count: int = 0
