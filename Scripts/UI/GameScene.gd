extends Control

const CONSOLE_HEIGHT: float = 320.0

# Popup dimensions (card aspect ratio 88:110 scaled up)
const POPUP_W: float = 280.0
const POPUP_H: float = 350.0
const POPUP_OFFSET: Vector2 = Vector2(16.0, -POPUP_H - 8.0)

var _controller: GameController
var _board_view: BoardView
var _console: CommandConsole
const AIFeedbackPanelScript = preload("res://Scripts/UI/AIFeedbackPanel.gd")
const MoveFeedbackBoxScript = preload("res://Scripts/UI/MoveFeedbackBox.gd")

var _ai: AIPlayer

# AI vs AI mode: both seats driven by the AI for human observation/analysis.
const AI_VS_AI_MOVE_DELAY := 3.0  # seconds between AI moves, for readability
var _ai0: AIPlayer = null
var _ai1: AIPlayer = null
var _ai_driving: bool = false

# Human-evaluation feedback flow (set from Main Menu toggle).
var _human_eval_enabled: bool = false
var _feedback_shown: bool = false
var _move_feedback_box = null

# Floating card art popup (lives outside the layout, draws on top)
var _popup: PanelContainer
var _popup_tex: TextureRect

# Local human seat — matches BoardView hand visibility (P1 faces, P2 backs).
const LOCAL_PLAYER_INDEX := 0

# "pvp" = no AI, "pvai" = P2 is AI (default when launched directly),
# "aivai" = both seats are AI (observation/analysis mode).
var _game_mode: String = "pvai"


func _ready() -> void:
	_game_mode = Engine.get_meta("game_mode", "pvai")
	_human_eval_enabled = bool(Engine.get_meta("human_eval_enabled", false))
	_setup_layout()
	_setup_popup()
	_setup_controller()
	if _game_mode == "pvai":
		_setup_ai()
	elif _game_mode == "aivai":
		_setup_ai_vs_ai()
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
	if _game_mode == "pvp" or _game_mode == "aivai":
		# pvp: no AI. aivai: both seats are driven manually from this scene, so
		# disable GameController's built-in single-seat AI trigger.
		_controller._ai_player_index = -1

	# Optional per-match deck overrides set by the Main Menu.
	var deck_config := {}
	var p1_deck := str(Engine.get_meta("p1_deck", ""))
	var p2_deck := str(Engine.get_meta("p2_deck", ""))
	if p1_deck != "":
		deck_config["p1_deck"] = p1_deck
	if p2_deck != "":
		deck_config["p2_deck"] = p2_deck

	if not deck_config.is_empty():
		_controller.skip_auto_start = true

	add_child(_controller)

	if not deck_config.is_empty():
		_controller.start_game_from_config(deck_config)


func _setup_ai() -> void:
	_ai = AIPlayer.new()
	_ai.name = "AIPlayer"
	_controller.add_child(_ai)
	_ai.setup(_controller, 1)
	if _human_eval_enabled:
		_setup_move_feedback_box()


func _setup_ai_vs_ai() -> void:
	# Two AI seats. Both run the same TurnSearch + agent pipeline as Player vs AI;
	# a per-move delay keeps the play watchable for human analysis.
	_ai0 = AIPlayer.new()
	_ai0.name = "AIPlayer0"
	_controller.add_child(_ai0)
	_ai0.setup(_controller, 0)
	_ai0._think_delay = AI_VS_AI_MOVE_DELAY

	_ai1 = AIPlayer.new()
	_ai1.name = "AIPlayer1"
	_controller.add_child(_ai1)
	_ai1.setup(_controller, 1)
	_ai1._think_delay = AI_VS_AI_MOVE_DELAY

	# Kick the driver once the scene is wired (deferred so it never runs inside a
	# board_updated emission before the tree has settled).
	call_deferred("_drive_ai_vs_ai")


# Serial driver: whichever seat can act takes one turn, then we poke for the
# next. The _ai_driving guard + each AIPlayer's _waiting_for_http flag ensure
# exactly one decision is in flight at a time despite repeated board_updated.
func _drive_ai_vs_ai() -> void:
	if _ai_driving:
		return
	var gs = _controller.gs if _controller else null
	if gs == null or gs.game_over:
		return
	if _ai0 == null or _ai1 == null:
		return
	if _ai0._waiting_for_http or _ai1._waiting_for_http:
		return
	var actor: AIPlayer = null
	if _ai0._can_act_now(gs) and not _ai0._legal_moves_for(gs).is_empty():
		actor = _ai0
	elif _ai1._can_act_now(gs) and not _ai1._legal_moves_for(gs).is_empty():
		actor = _ai1
	if actor == null:
		return
	_ai_driving = true
	await actor.take_turn()
	while actor != null and actor._waiting_for_http:
		await get_tree().process_frame
	_ai_driving = false
	call_deferred("_drive_ai_vs_ai")


func _setup_move_feedback_box() -> void:
	# Floating live per-move feedback widget, pinned to the top-right corner so it
	# sits over empty board space without disturbing the main layout.
	_move_feedback_box = MoveFeedbackBoxScript.new()
	_move_feedback_box.name = "MoveFeedbackBox"
	_move_feedback_box.configure(Callable(self, "_current_game_id"))
	add_child(_move_feedback_box)
	# Pin near the bottom-right corner, sitting just above the command console
	# (which occupies the bottom CONSOLE_HEIGHT px) so it overlays empty space.
	_move_feedback_box.anchor_left = 1.0
	_move_feedback_box.anchor_right = 1.0
	_move_feedback_box.anchor_top = 1.0
	_move_feedback_box.anchor_bottom = 1.0
	_move_feedback_box.offset_left = -226
	_move_feedback_box.offset_right = -16
	_move_feedback_box.offset_top = -(206)
	_move_feedback_box.offset_bottom = -(16)
	_ai.ai_move_completed.connect(_move_feedback_box.on_ai_move)


func _current_game_id() -> String:
	if _controller and _controller.gs and not _controller.gs.game_session_id.is_empty():
		return _controller.gs.game_session_id
	return "game"


func _wire_signals() -> void:
	_controller.game_log_message.connect(_on_game_log)
	_controller.board_updated.connect(_on_board_updated)
	_console.command_submitted.connect(_on_command_submitted)
	_board_view.card_hovered.connect(_on_card_hovered)
	_board_view.card_unhovered.connect(_on_card_unhovered)
	_board_view.card_clicked.connect(_on_card_clicked)
	if _controller.gs:
		_on_board_updated()


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
	if gs.game_over:
		_maybe_show_feedback(gs)
		return
	if _game_mode == "aivai":
		call_deferred("_drive_ai_vs_ai")


func _maybe_show_feedback(gs: GameState) -> void:
	if _feedback_shown:
		return
	if not _human_eval_enabled or _game_mode != "pvai":
		return
	if gs.winner_index < 0:
		return
	_feedback_shown = true
	if _move_feedback_box != null:
		_move_feedback_box.visible = false
	var panel = AIFeedbackPanelScript.new()
	panel.name = "AIFeedbackPanel"
	add_child(panel)
	var game_id := gs.game_session_id if not gs.game_session_id.is_empty() else "game"
	panel.show_for_game(game_id)


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
	if _is_opponent_hidden(inst):
		_popup_tex.texture = _load_card_back_texture()
	else:
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


func _on_card_clicked(inst: CardInstance) -> void:
	if _is_opponent_hidden(inst):
		return
	_console.append_to_input(inst.instance_id)


func _is_opponent_hidden(inst: CardInstance) -> bool:
	return inst.is_face_down and inst.owner_index != LOCAL_PLAYER_INDEX


func _load_card_back_texture() -> Texture2D:
	return load("res://Assets/Champ_Card.jpg")
