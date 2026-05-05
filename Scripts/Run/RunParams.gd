extends Resource
class_name RunParams

## Player run health at run start (not TCG lane health).
@export var starting_player_health: int = 100

## Max rounds to survive for victory (0 = no cap).
@export var max_rounds: int = 0

## Flat damage to player run health on round loss.
@export var damage_on_loss_flat: int = 5

## When use_flat_damage is false: damage = enemy_survivor_count * damage_per_survivor (stub outcome).
@export var damage_per_survivor: int = 2

@export var use_flat_damage: bool = true

## Stub combat: force outcomes (always_win wins over always_lose).
@export var stub_always_win: bool = false
@export var stub_always_lose: bool = false

## Enemy survivors assigned on stub loss (for survivor-based damage).
@export var stub_enemy_survivors_on_loss: int = 3

## Optional heal when winning a round (clamped to starting_player_health).
@export var healing_on_round_win: int = 0

static func default_params() -> RunParams:
	return RunParams.new()
