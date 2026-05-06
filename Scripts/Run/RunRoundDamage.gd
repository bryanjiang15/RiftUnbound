extends RefCounted
class_name RunRoundDamage

## Stateless utility for computing player run-health damage after a lost round.
##
## Two modes governed by RunParams.use_flat_damage:
##   true  → fixed `damage_on_loss_flat` regardless of enemy survivors.
##   false → `enemy_survivor_count * damage_per_survivor` (survivor-scaled).

## Returns the damage to subtract from player run health based on `params` and the
## round `outcome`. Always returns 0 when the player won.
static func damage_on_loss(params: RunParams, outcome: CombatOutcome) -> int:
	if outcome.player_won_round:
		return 0
	if params.use_flat_damage:
		return params.damage_on_loss_flat
	return outcome.enemy_survivor_count * params.damage_per_survivor
