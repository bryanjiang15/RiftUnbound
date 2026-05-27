extends Control

const CONSOLE_HEIGHT: float = 320.0

# Popup dimensions (card aspect ratio 88:110 scaled up)
const POPUP_W: float = 280.0
const POPUP_H: float = 350.0
const POPUP_OFFSET: Vector2 = Vector2(16.0, -POPUP_H - 8.0)

var _controller: GameController
var _board_view: BoardView
var _console: CommandConsole
var _ai: AIPlayer

# Floating card art popup (lives outside the layout, draws on top)
var _popup: PanelContainer
var _popup_tex: TextureRect

# "pvp" = no AI, "pvai" = P2 is AI (default when launched directly)
var _game_mode: String = "pvai"


func _ready() -> void:
	_game_mode = Engine.get_meta("game_mode", "pvai")
	_setup_layout()
	_setup_popup()
	_setup_controller()
	if _game_mode == "pvai":
		_setup_ai()
	_wire_signals()


func _setup_layout() -> void:
	var bg_color = ColorRect.new()
	bg_color.color = Color(0.05, 0.05, 0.08)
	bg_color.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(bg_color)

	var outer = VBoxContainer.new()
	outer.name = "OuterLayout"
	outer.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	outer.add_theme_constant_override("separation", 0)
	add_child(outer)

	_board_view = BoardView.new()
	_board_view.name = "BoardView"
	_board_view.size_flags_vertical = Control.SIZE_EXPAND_FILL
	outer.add_child(_board_view)

	_console = CommandConsole.new()
	_console.name = "CommandConsole"
	_console.custom_minimum_size = Vector2(0, CONSOLE_HEIGHT)
	outer.add_child(_console)


func _setup_popup() -> void:
	_popup = PanelContainer.new()
	_popup.name = "CardPopup"
	_popup.custom_minimum_size = Vector2(POPUP_W, POPUP_H)
	_popup.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_popup.visible = false

	var sb := StyleBoxFlat.new()
	sb.bg_color = Color(0.06, 0.06, 0.09, 0.97)
	sb.border_color = Color(0.50, 0.50, 0.65)
	sb.set_border_width_all(2)
	sb.set_corner_radius_all(6)
	sb.shadow_color = Color(0.0, 0.0, 0.0, 0.60)
	sb.shadow_size = 8
	_popup.add_theme_stylebox_override("panel", sb)

	_popup_tex = TextureRect.new()
	_popup_tex.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_popup_tex.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_popup_tex.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	_popup_tex.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_popup_tex.size_flags_vertical   = Control.SIZE_EXPAND_FILL
	_popup_tex.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_popup.add_child(_popup_tex)

	# Add as top-level child so it renders above everything else
	add_child(_popup)


func _setup_controller() -> void:
	_controller = GameController.new()
	_controller.name = "GameController"
	if _game_mode == "pvp":
		_controller._ai_player_index = -1
	add_child(_controller)


func _setup_ai() -> void:
	_ai = AIPlayer.new()
	_ai.name = "AIPlayer"
	_controller.add_child(_ai)
	_ai.setup(_controller, 1)


func _wire_signals() -> void:
	_controller.game_log_message.connect(_on_game_log)
	_controller.board_updated.connect(_on_board_updated)
	_console.command_submitted.connect(_on_command_submitted)
	_board_view.card_hovered.connect(_on_card_hovered)
	_board_view.card_unhovered.connect(_on_card_unhovered)


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
	if gs.mulligan_phase:
		if not gs.mulligan_done[0]:
			active = 0
		elif not gs.mulligan_done[1]:
			active = 1
	_console.update_prompt(active, gs.is_showdown_state())


func _on_command_submitted(player_index: int, text: String) -> void:
	_controller.submit_command(player_index, text)


func _on_card_hovered(inst: CardInstance) -> void:
	var def := inst.definition
	var img_path: String = "res://Assets/" + def.image if def.image != "" \
		else "res://Assets/Champ_Card.jpg"
	if not ResourceLoader.exists(img_path):
		img_path = "res://Assets/Champ_Card.jpg"
	_popup_tex.texture = load(img_path)

	# Position popup above-right of cursor, clamped to viewport
	var mouse := get_global_mouse_position()
	var vp    := get_viewport().get_visible_rect().size
	var pos   := mouse + POPUP_OFFSET
	pos.x = clamp(pos.x, 4.0, vp.x - POPUP_W - 4.0)
	pos.y = clamp(pos.y, 4.0, vp.y - POPUP_H - 4.0)
	_popup.set_position(pos)
	_popup.set_size(Vector2(POPUP_W, POPUP_H))
	_popup.visible = true


func _on_card_unhovered() -> void:
	_popup.visible = false
	_popup_tex.texture = null
