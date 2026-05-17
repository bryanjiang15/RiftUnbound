class_name CommandParser

# Thin wrapper that routes raw text from a player to GameController.
# GameController handles all parsing and validation internally.
# This class provides the public API used by both the console UI and AI player.

var controller: GameController


func _init(gc: GameController) -> void:
	controller = gc


func submit_command(player_index: int, raw_text: String) -> void:
	if controller == null:
		push_error("CommandParser: no GameController attached")
		return
	controller.submit_command(player_index, raw_text)
