extends Resource
class_name PlanningParams

## Uniform equipment slots per champion until §4.6 locks per-champion curves.
@export var equipment_slots_per_champion: int = 3

## Phase C stub: 1–3 player champions on board without economy.
@export var max_player_champions_on_board: int = 3

## If true, locking planning fails while no player champion is placed.
@export var require_at_least_one_player_champion: bool = true

static func default_params() -> PlanningParams:
	return PlanningParams.new()
