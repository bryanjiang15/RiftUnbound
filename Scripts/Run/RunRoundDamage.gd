extends RefCounted
class_name RunRoundDamage

## Damage applied to player run health when the round is lost (§4.2 placeholder).
static func damage_on_loss(params: RunParams, outcome: CombatOutcome) -> int:
	if outcome.player_won_round:
		return 0
	if params.use_flat_damage:
		return params.damage_on_loss_flat
	return outcome.enemy_survivor_count * params.damage_per_survivor
