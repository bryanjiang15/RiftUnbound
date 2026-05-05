extends RefCounted
class_name CombatOutcome

## Result of combat resolution (stub until Phase D).
var player_won_round: bool = true

## Used by RunRoundDamage when use_flat_damage is false.
var enemy_survivor_count: int = 0
