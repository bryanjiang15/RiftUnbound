extends Control

const CONSOLE_HEIGHT: float = 320.0

var _controller: GameController
var _board_view: BoardView
var _console: CommandConsole
var _ai: AIPlayer


func _ready() -> void:
	_setup_layout()
	_setup_controller()
	_setup_ai()
	_wire_signals()


func _setup_layout() -> void:
	# Full-screen dark background
	var bg_color = ColorRect.new()
	bg_color.color = Color(0.05, 0.05, 0.08)
	bg_color.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(bg_color)

	# Outer VBox: Board (top, expands) + Console (bottom, fixed height)
	var outer = VBoxContainer.new()
	outer.name = "OuterLayout"
	outer.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	outer.add_theme_constant_override("separation", 0)
	add_child(outer)

	# Board view
	_board_view = BoardView.new()
	_board_view.name = "BoardView"
	_board_view.size_flags_vertical = Control.SIZE_EXPAND_FILL
	outer.add_child(_board_view)

	# Console
	_console = CommandConsole.new()
	_console.name = "CommandConsole"
	_console.custom_minimum_size = Vector2(0, CONSOLE_HEIGHT)
	outer.add_child(_console)


func _setup_controller() -> void:
	_controller = GameController.new()
	_controller.name = "GameController"
	add_child(_controller)


func _setup_ai() -> void:
	_ai = AIPlayer.new()
	_ai.name = "AIPlayer"
	_controller.add_child(_ai)
	_ai.setup(_controller, 1)


func _wire_signals() -> void:
	# Pipe controller log messages → console
	_controller.game_log_message.connect(_on_game_log)
	# Pipe controller board updates → board view refresh
	_controller.board_updated.connect(_on_board_updated)
	# Pipe console commands → controller
	_console.command_submitted.connect(_on_command_submitted)


func _on_game_log(text: String) -> void:
	_console.add_line(text)
	if _controller.gs and not _controller.gs.game_over:
		_update_console_prompt(_controller.gs)


func _on_board_updated() -> void:
	if _controller.gs == null:
		return
	var gs := _controller.gs
	_board_view.refresh(gs)
	_update_console_prompt(gs)


func _update_console_prompt(gs: GameState) -> void:
	var active := gs.turn_player_index
	if not gs.pending_prompt.is_empty():
		active = gs.pending_prompt.get("player_index", active)
	# During mulligan, prompt whichever player hasn't finished yet
	if gs.mulligan_phase:
		if not gs.mulligan_done[0]:
			active = 0
		elif not gs.mulligan_done[1]:
			active = 1
	_console.update_prompt(active, gs.is_showdown_state())


func _on_command_submitted(player_index: int, text: String) -> void:
	_controller.submit_command(player_index, text)
