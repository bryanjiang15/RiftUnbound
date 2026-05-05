extends Resource
class_name CombatStats

## Shared combat numbers for definitions and runtime copies. See ChampionData / ChampionInstance.

@export var max_health: int = 0
@export var current_health: int = 0
@export var attack: int = 0
@export var defense: int = 0
@export var speed: int = 0

## Runtime copy; does not share sub-resources with the source.
func duplicate_for_instance() -> CombatStats:
	var c := duplicate(true) as CombatStats
	return c
