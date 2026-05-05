extends RefCounted
class_name RunState

var run_id: String = ""
var current_round_index: int = 1
var player_run_health: int = 0
var is_terminal: bool = false
var params: RunParams

func _init(p_params: RunParams) -> void:
	params = p_params
