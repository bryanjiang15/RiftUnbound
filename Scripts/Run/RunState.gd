extends RefCounted
class_name RunState

## Mutable snapshot of all dynamic run-level data for one active run.
##
## Created and owned by RunController.start_run(); read by RunHud and RunController
## to display status and enforce terminal conditions. Replaced entirely on restart
## rather than mutated across runs.

var run_id: String = ""
var current_round_index: int = 1
var player_run_health: int = 0
var is_terminal: bool = false
var params: RunParams

func _init(p_params: RunParams) -> void:
	params = p_params
