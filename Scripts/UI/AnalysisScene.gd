extends Control

# Post-game Analysis UI: browse agent_memory.db decisions via the AI agent
# (localhost:8765), restore checkpoints onto BoardView, step ply-by-ply through
# played / candidate / counterfactual lines, and run CF / failure-report analysis.

const AGENT_PORT := 8765
const AnalysisStateCodecScript = preload("res://Scripts/AI/AnalysisStateCodec.gd")
const AnalysisTimelineScript = preload("res://Scripts/UI/AnalysisTimeline.gd")
const BoardViewScript = preload("res://Scripts/UI/BoardView.gd")

enum ReqMode { NONE, LIST, DETAIL, COUNTERFACTUAL, FAILURE_REPORT, HEALTH, PRIOR_RUNS, CHECKPOINT, PRIOR_RUN_ONE }

var _http: HTTPRequest
var _http_bg: HTTPRequest
var _req_mode: ReqMode = ReqMode.NONE
var _busy: bool = false

# Filters / list
var _game_id_edit: LineEdit
var _replay_only_check: CheckBox
var _limit_spin: SpinBox
var _status_label: Label
var _decision_list: ItemList
var _refresh_btn: Button
var _listed: Array = []  # raw decision dicts matching ItemList indices

# Detail / actions
var _detail_label: RichTextLabel
var _results_label: RichTextLabel
var _open_board_btn: Button
var _run_cf_btn: Button
var _run_fail_btn: Button
var _back_menu_btn: Button
var _preset_picker: OptionButton
var _horizon_spin: SpinBox
var _hor_lbl: Label
var _until_turn_spin: SpinBox
var _until_lbl: Label
var _target_picker: OptionButton
var _bf_edit: LineEdit
var _persist_check: CheckBox
var _oracle_label: Label
var _prior_runs_picker: OptionButton
var _prior_runs: Array = []

# Board / stepping
var _board_view: BoardView
var _line_picker: OptionButton
var _move_list: ItemList
var _step_label: Label
var _prev_btn: Button
var _next_btn: Button
var _board_panel: Control
var _oracle_board_note: Label

var _selected: Dictionary = {}
var _detail: Dictionary = {}
var _root_gs: GameState = null
var _timeline: AnalysisTimeline = null
var _line_options: Array = []  # [{id, label, moves, source, path?}]
var _last_cf_result: Dictionary = {}
var _pending_detail_then_board: bool = false


func _ready() -> void:
	_timeline = AnalysisTimelineScript.new()
	_http = HTTPRequest.new()
	_http.timeout = 600.0  # CF can spawn headless Godot
	add_child(_http)
	_http.request_completed.connect(_on_request_completed)
	_http_bg = HTTPRequest.new()
	_http_bg.timeout = 60.0
	add_child(_http_bg)
	_http_bg.request_completed.connect(_on_bg_request_completed)
	_build_ui()
	_set_busy(false)
	_check_health()


func _agent_base_url() -> String:
	var host := "127.0.0.1" if OS.get_name() == "Windows" else "localhost"
	return "http://%s:%d" % [host, AGENT_PORT]


# ── UI ────────────────────────────────────────────────────────────────────────


func _build_ui() -> void:
	var bg := ColorRect.new()
	bg.color = Color(0.04, 0.04, 0.07)
	bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(bg)

	var root := VBoxContainer.new()
	root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	root.add_theme_constant_override("separation", 8)
	root.add_theme_constant_override("margin_left", 12)
	root.offset_left = 12
	root.offset_right = -12
	root.offset_top = 10
	root.offset_bottom = -10
	add_child(root)

	root.add_child(_build_header())
	root.add_child(_build_filters())

	var split := VSplitContainer.new()
	split.size_flags_vertical = Control.SIZE_EXPAND_FILL
	split.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	split.split_offset = 220
	root.add_child(split)

	var mid := HSplitContainer.new()
	mid.size_flags_vertical = Control.SIZE_EXPAND_FILL
	mid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	mid.size_flags_stretch_ratio = 0.55
	mid.custom_minimum_size = Vector2(0, 160)
	mid.split_offset = 360
	split.add_child(mid)

	mid.add_child(_build_list_panel())
	mid.add_child(_build_detail_panel())

	_board_panel = _build_board_panel()
	_board_panel.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_board_panel.size_flags_stretch_ratio = 2.4
	_board_panel.custom_minimum_size = Vector2(0, 420)
	split.add_child(_board_panel)


func _build_header() -> Control:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 16)

	var title := Label.new()
	title.text = "Post-Game Analysis"
	title.add_theme_font_size_override("font_size", 20)
	title.add_theme_color_override("font_color", Color(0.92, 0.93, 0.96))
	row.add_child(title)

	_status_label = Label.new()
	_status_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_status_label.add_theme_font_size_override("font_size", 14)
	_status_label.add_theme_color_override("font_color", Color(0.55, 0.60, 0.72))
	_status_label.text = "Checking agent…"
	row.add_child(_status_label)

	_back_menu_btn = Button.new()
	_back_menu_btn.text = "Main Menu"
	_back_menu_btn.pressed.connect(_on_back_menu)
	row.add_child(_back_menu_btn)
	return row


func _build_filters() -> Control:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)

	var gid_lbl := Label.new()
	gid_lbl.text = "game_id"
	gid_lbl.add_theme_color_override("font_color", Color(0.65, 0.70, 0.80))
	row.add_child(gid_lbl)

	_game_id_edit = LineEdit.new()
	_game_id_edit.placeholder_text = "(all games)"
	_game_id_edit.custom_minimum_size = Vector2(220, 0)
	row.add_child(_game_id_edit)

	_replay_only_check = CheckBox.new()
	_replay_only_check.text = "Replay-eligible only"
	_replay_only_check.button_pressed = true
	row.add_child(_replay_only_check)

	var lim_lbl := Label.new()
	lim_lbl.text = "limit"
	lim_lbl.add_theme_color_override("font_color", Color(0.65, 0.70, 0.80))
	row.add_child(lim_lbl)

	_limit_spin = SpinBox.new()
	_limit_spin.min_value = 10
	_limit_spin.max_value = 500
	_limit_spin.value = 100
	_limit_spin.custom_minimum_size = Vector2(90, 0)
	row.add_child(_limit_spin)

	_refresh_btn = Button.new()
	_refresh_btn.text = "Refresh"
	_refresh_btn.pressed.connect(_on_refresh)
	row.add_child(_refresh_btn)
	return row


func _build_list_panel() -> Control:
	var panel := PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.size_flags_vertical = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override("panel", _panel_sb())

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 6)
	panel.add_child(vbox)

	var lbl := Label.new()
	lbl.text = "Decisions"
	lbl.add_theme_font_size_override("font_size", 16)
	lbl.add_theme_color_override("font_color", Color(0.75, 0.78, 0.88))
	vbox.add_child(lbl)

	_decision_list = ItemList.new()
	_decision_list.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_decision_list.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_decision_list.item_selected.connect(_on_decision_selected)
	vbox.add_child(_decision_list)
	return panel


func _build_detail_panel() -> Control:
	var panel := PanelContainer.new()
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.size_flags_vertical = Control.SIZE_EXPAND_FILL
	panel.add_theme_stylebox_override("panel", _panel_sb())

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 4)
	panel.add_child(vbox)

	var lbl := Label.new()
	lbl.text = "Detail"
	lbl.add_theme_font_size_override("font_size", 14)
	lbl.add_theme_color_override("font_color", Color(0.75, 0.78, 0.88))
	vbox.add_child(lbl)

	_detail_label = RichTextLabel.new()
	_detail_label.bbcode_enabled = true
	_detail_label.fit_content = false
	_detail_label.scroll_active = true
	_detail_label.custom_minimum_size = Vector2(0, 48)
	_detail_label.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_detail_label.add_theme_color_override("default_color", Color(0.80, 0.82, 0.90))
	_detail_label.text = "Select a decision."
	vbox.add_child(_detail_label)

	var actions := HBoxContainer.new()
	actions.add_theme_constant_override("separation", 8)
	vbox.add_child(actions)

	_open_board_btn = Button.new()
	_open_board_btn.text = "Open on Board"
	_open_board_btn.pressed.connect(_on_open_board)
	actions.add_child(_open_board_btn)

	_run_cf_btn = Button.new()
	_run_cf_btn.text = "Run Analysis"
	_run_cf_btn.pressed.connect(_on_run_cf)
	actions.add_child(_run_cf_btn)

	_run_fail_btn = Button.new()
	_run_fail_btn.text = "Failure Report"
	_run_fail_btn.pressed.connect(_on_run_failure)
	actions.add_child(_run_fail_btn)

	# Rollout configuration row
	var cfg := HBoxContainer.new()
	cfg.add_theme_constant_override("separation", 8)
	vbox.add_child(cfg)

	var preset_lbl := Label.new()
	preset_lbl.text = "Preset"
	preset_lbl.add_theme_color_override("font_color", Color(0.65, 0.70, 0.80))
	cfg.add_child(preset_lbl)
	_preset_picker = OptionButton.new()
	_preset_picker.add_item("Deep", 0)
	_preset_picker.add_item("Fast", 1)
	_preset_picker.select(0)
	cfg.add_child(_preset_picker)

	_hor_lbl = Label.new()
	_hor_lbl.text = "Future turns"
	_hor_lbl.add_theme_color_override("font_color", Color(0.65, 0.70, 0.80))
	cfg.add_child(_hor_lbl)
	_horizon_spin = SpinBox.new()
	_horizon_spin.min_value = 1
	_horizon_spin.max_value = 6
	_horizon_spin.value = 4
	_horizon_spin.custom_minimum_size = Vector2(70, 0)
	cfg.add_child(_horizon_spin)

	_until_lbl = Label.new()
	_until_lbl.text = "Until turn"
	_until_lbl.add_theme_color_override("font_color", Color(0.65, 0.70, 0.80))
	_until_lbl.visible = false
	cfg.add_child(_until_lbl)
	_until_turn_spin = SpinBox.new()
	_until_turn_spin.min_value = 1
	_until_turn_spin.max_value = 99
	_until_turn_spin.value = 4
	_until_turn_spin.custom_minimum_size = Vector2(70, 0)
	_until_turn_spin.visible = false
	_until_turn_spin.tooltip_text = "Simulate from this decision until that game turn ends"
	cfg.add_child(_until_turn_spin)

	var tgt_lbl := Label.new()
	tgt_lbl.text = "Target"
	tgt_lbl.add_theme_color_override("font_color", Color(0.65, 0.70, 0.80))
	cfg.add_child(tgt_lbl)
	_target_picker = OptionButton.new()
	_target_picker.add_item("Win game", 0)
	_target_picker.add_item("Control battlefield", 1)
	_target_picker.add_item("Best position until turn N", 2)
	_target_picker.add_item("Max VP lead until turn N", 3)
	_target_picker.item_selected.connect(_on_target_changed)
	cfg.add_child(_target_picker)

	_bf_edit = LineEdit.new()
	_bf_edit.placeholder_text = "battlefield-id"
	_bf_edit.custom_minimum_size = Vector2(140, 0)
	_bf_edit.visible = false
	cfg.add_child(_bf_edit)

	_persist_check = CheckBox.new()
	_persist_check.text = "Persist"
	_persist_check.button_pressed = true
	cfg.add_child(_persist_check)

	_oracle_label = Label.new()
	_oracle_label.text = "Oracle hidden info"
	_oracle_label.add_theme_color_override("font_color", Color(0.85, 0.70, 0.35))
	cfg.add_child(_oracle_label)

	var prior_row := HBoxContainer.new()
	prior_row.add_theme_constant_override("separation", 8)
	vbox.add_child(prior_row)
	var prior_lbl := Label.new()
	prior_lbl.text = "Prior runs"
	prior_lbl.add_theme_color_override("font_color", Color(0.65, 0.70, 0.80))
	prior_row.add_child(prior_lbl)
	_prior_runs_picker = OptionButton.new()
	_prior_runs_picker.custom_minimum_size = Vector2(320, 0)
	_prior_runs_picker.item_selected.connect(_on_prior_run_selected)
	prior_row.add_child(_prior_runs_picker)

	var res_lbl := Label.new()
	res_lbl.text = "Analysis Results"
	res_lbl.add_theme_font_size_override("font_size", 14)
	res_lbl.add_theme_color_override("font_color", Color(0.70, 0.74, 0.85))
	vbox.add_child(res_lbl)

	_results_label = RichTextLabel.new()
	_results_label.bbcode_enabled = true
	_results_label.fit_content = false
	_results_label.scroll_active = true
	_results_label.custom_minimum_size = Vector2(0, 48)
	_results_label.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_results_label.add_theme_color_override("default_color", Color(0.72, 0.78, 0.72))
	_results_label.text = ""
	vbox.add_child(_results_label)
	return panel


func _build_board_panel() -> Control:
	var panel := PanelContainer.new()
	panel.add_theme_stylebox_override("panel", _panel_sb())

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 6)
	panel.add_child(vbox)

	var controls := HBoxContainer.new()
	controls.add_theme_constant_override("separation", 8)
	vbox.add_child(controls)

	var line_lbl := Label.new()
	line_lbl.text = "Line"
	line_lbl.add_theme_color_override("font_color", Color(0.65, 0.70, 0.80))
	controls.add_child(line_lbl)

	_line_picker = OptionButton.new()
	_line_picker.custom_minimum_size = Vector2(280, 0)
	_line_picker.item_selected.connect(_on_line_selected)
	controls.add_child(_line_picker)

	_prev_btn = Button.new()
	_prev_btn.text = "◀ Prev"
	_prev_btn.pressed.connect(_on_step_prev)
	controls.add_child(_prev_btn)

	_step_label = Label.new()
	_step_label.text = "Step —"
	_step_label.custom_minimum_size = Vector2(160, 0)
	_step_label.add_theme_color_override("font_color", Color(0.85, 0.88, 0.95))
	controls.add_child(_step_label)

	_next_btn = Button.new()
	_next_btn.text = "Next ▶"
	_next_btn.pressed.connect(_on_step_next)
	controls.add_child(_next_btn)

	var board_row := HSplitContainer.new()
	board_row.size_flags_vertical = Control.SIZE_EXPAND_FILL
	board_row.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	board_row.split_offset = -220
	vbox.add_child(board_row)

	_board_view = BoardViewScript.new()
	_board_view.reveal_all_hands = true
	_board_view.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_board_view.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_board_view.custom_minimum_size = Vector2(400, 360)
	board_row.add_child(_board_view)

	var moves_wrap := VBoxContainer.new()
	moves_wrap.custom_minimum_size = Vector2(220, 0)
	board_row.add_child(moves_wrap)

	_oracle_board_note = Label.new()
	_oracle_board_note.text = "Hands revealed = oracle analysis view (not public info)"
	_oracle_board_note.add_theme_font_size_override("font_size", 11)
	_oracle_board_note.add_theme_color_override("font_color", Color(0.85, 0.70, 0.35))
	moves_wrap.add_child(_oracle_board_note)

	var moves_lbl := Label.new()
	moves_lbl.text = "Moves"
	moves_lbl.add_theme_color_override("font_color", Color(0.70, 0.74, 0.85))
	moves_wrap.add_child(moves_lbl)

	_move_list = ItemList.new()
	_move_list.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_move_list.item_selected.connect(_on_move_jumped)
	moves_wrap.add_child(_move_list)
	return panel


func _panel_sb() -> StyleBoxFlat:
	var sb := StyleBoxFlat.new()
	sb.bg_color = Color(0.07, 0.07, 0.10, 0.95)
	sb.border_color = Color(0.28, 0.30, 0.40)
	sb.set_border_width_all(1)
	sb.set_corner_radius_all(6)
	sb.set_content_margin_all(10)
	return sb


# ── HTTP ──────────────────────────────────────────────────────────────────────


func _set_busy(busy: bool) -> void:
	_busy = busy
	if _refresh_btn:
		_refresh_btn.disabled = busy
	if _open_board_btn:
		_open_board_btn.disabled = busy or _selected.is_empty()
	if _run_cf_btn:
		_run_cf_btn.disabled = busy or _selected.is_empty()
	if _run_fail_btn:
		_run_fail_btn.disabled = busy or _selected.is_empty()
	if _preset_picker:
		_preset_picker.disabled = busy
	if _horizon_spin:
		_horizon_spin.editable = not busy
	if _until_turn_spin:
		_until_turn_spin.editable = not busy
	if _target_picker:
		_target_picker.disabled = busy
	if _prior_runs_picker:
		_prior_runs_picker.disabled = busy
	if _persist_check:
		_persist_check.disabled = busy


func _moves_key(moves) -> String:
	if typeof(moves) != TYPE_ARRAY:
		return ""
	var parts: PackedStringArray = PackedStringArray()
	for m in moves:
		parts.append(str(m))
	return "|".join(parts)


func _maybe_add_cf_line(line, prefix: String, seen_keys: Dictionary = {}) -> void:
	if typeof(line) != TYPE_DICTIONARY:
		return
	var moves = line.get("canonical_moves", line.get("moves", []))
	if typeof(moves) != TYPE_ARRAY or moves.is_empty():
		return
	var key := _moves_key(moves)
	if seen_keys.has(key):
		return
	seen_keys[key] = true
	var lid := str(line.get("line_id", prefix))
	var label := "%s: %s (%d moves)" % [prefix, lid, moves.size()]
	_line_options.append({"id": lid, "label": label, "moves": moves, "source": "cf"})
	_line_picker.add_item(label)


func _check_health() -> void:
	_req_mode = ReqMode.HEALTH
	_set_busy(true)
	var err := _http.request(_agent_base_url() + "/health")
	if err != OK:
		_set_busy(false)
		_status_label.add_theme_color_override("font_color", Color(0.90, 0.45, 0.45))
		_status_label.text = "Cannot reach agent on :%d — start ai_agent (uvicorn … --port 8765)" % AGENT_PORT


func _on_refresh() -> void:
	_load_decisions()


func _load_decisions() -> void:
	if _busy:
		return
	_req_mode = ReqMode.LIST
	_set_busy(true)
	_status_label.add_theme_color_override("font_color", Color(0.55, 0.60, 0.72))
	_status_label.text = "Loading decisions…"
	var params := "limit=%d&offset=0&replay_only=%s" % [
		int(_limit_spin.value),
		"true" if _replay_only_check.button_pressed else "false",
	]
	var gid := _game_id_edit.text.strip_edges()
	if gid != "":
		params += "&game_id=" + gid.uri_encode()
	var err := _http.request(_agent_base_url() + "/analysis/decisions?" + params)
	if err != OK:
		_set_busy(false)
		_status_label.add_theme_color_override("font_color", Color(0.90, 0.45, 0.45))
		_status_label.text = "Request failed to start."


func _fetch_detail(then_open_board: bool = false) -> void:
	if _selected.is_empty() or _busy:
		return
	_pending_detail_then_board = then_open_board
	_req_mode = ReqMode.DETAIL
	_set_busy(true)
	_status_label.text = "Loading decision…"
	# List-click omits analysis_state. Open-on-board without a matching
	# detail still asks for it so restore can proceed in one round-trip.
	var include_state := "true" if then_open_board else "false"
	var url := "%s/analysis/decision?game_id=%s&turn=%d&decision_index=%d&include_state=%s" % [
		_agent_base_url(),
		str(_selected.get("game_id", "")).uri_encode(),
		int(_selected.get("turn", 0)),
		int(_selected.get("decision_index", 0)),
		include_state,
	]
	var err := _http.request(url)
	if err != OK:
		_set_busy(false)
		_status_label.text = "Detail request failed to start."


func _fetch_checkpoint() -> void:
	if _selected.is_empty() or _busy:
		return
	_req_mode = ReqMode.CHECKPOINT
	_set_busy(true)
	_status_label.text = "Loading board checkpoint…"
	var url := "%s/analysis/checkpoint?game_id=%s&turn=%d&decision_index=%d" % [
		_agent_base_url(),
		str(_selected.get("game_id", "")).uri_encode(),
		int(_selected.get("turn", 0)),
		int(_selected.get("decision_index", 0)),
	]
	var err := _http.request(url)
	if err != OK:
		_set_busy(false)
		_status_label.text = "Checkpoint request failed to start."


func _on_target_changed(index: int) -> void:
	_bf_edit.visible = index == 1
	var until_score := index == 2 or index == 3
	if _hor_lbl:
		_hor_lbl.visible = not until_score
	if _horizon_spin:
		_horizon_spin.visible = not until_score
	if _until_lbl:
		_until_lbl.visible = until_score
	if _until_turn_spin:
		_until_turn_spin.visible = until_score
	if until_score:
		_sync_until_turn_bounds()


func _sync_until_turn_bounds() -> void:
	if _until_turn_spin == null:
		return
	var cur := maxi(int(_selected.get("turn", 1)), 1)
	_until_turn_spin.min_value = cur
	_until_turn_spin.max_value = cur + 6
	if int(_until_turn_spin.value) < cur:
		_until_turn_spin.value = mini(cur + 2, cur + 6)
	elif int(_until_turn_spin.value) > cur + 6:
		_until_turn_spin.value = cur + 6


func _build_cf_request_body() -> Dictionary:
	var body := {
		"game_id": str(_selected.get("game_id", "")),
		"turn": int(_selected.get("turn", 0)),
		"decision_index": int(_selected.get("decision_index", 0)),
		"persist": bool(_persist_check.button_pressed) if _persist_check != null else true,
		"mode": "outcome_rollout",
		"preset": "fast" if _preset_picker != null and _preset_picker.selected == 1 else "deep",
		"future_player_turns": int(_horizon_spin.value) if _horizon_spin != null else 4,
	}
	var tgt := {"kind": "win"}
	var tsel := int(_target_picker.selected) if _target_picker != null else 0
	if tsel == 1:
		tgt = {
			"kind": "control_battlefield",
			"battlefield_id": str(_bf_edit.text).strip_edges(),
		}
	elif tsel == 2 or tsel == 3:
		var until_turn := int(_until_turn_spin.value) if _until_turn_spin != null else 4
		var cur_turn := int(body["turn"])
		until_turn = maxi(until_turn, cur_turn)
		body["future_player_turns"] = clampi(until_turn - cur_turn + 1, 1, 6)
		body["until_turn_number"] = until_turn
		tgt = {
			"kind": "max_score_after_turns",
			"until_turn": until_turn,
			"metric": "score_diff" if tsel == 3 else "position",
			"label": "max_score_lead_after_turns" if tsel == 3 else "best_position_until_turn",
		}
	body["target"] = tgt
	return body


func _on_run_cf() -> void:
	if _selected.is_empty() or _busy:
		return
	_req_mode = ReqMode.COUNTERFACTUAL
	_set_busy(true)
	_status_label.text = "Running outcome rollout (may take a while)…"
	_results_label.text = "Running multi-turn outcome analysis…"
	var body := _build_cf_request_body()
	var err := _http.request(
		_agent_base_url() + "/analysis/counterfactual",
		["Content-Type: application/json"],
		HTTPClient.METHOD_POST,
		JSON.stringify(body),
	)
	if err != OK:
		_set_busy(false)
		_status_label.text = "CF request failed to start."


func _fetch_prior_runs() -> void:
	if _selected.is_empty() or _http_bg == null:
		return
	var url := "%s/analysis/counterfactual-runs?game_id=%s&turn=%d&decision_index=%d&limit=20" % [
		_agent_base_url(),
		str(_selected.get("game_id", "")).uri_encode(),
		int(_selected.get("turn", 0)),
		int(_selected.get("decision_index", 0)),
	]
	_http_bg.request(url)


func _on_bg_request_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		return
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if typeof(parsed) != TYPE_DICTIONARY:
		return
	_populate_prior_runs(parsed.get("runs", []))


func _on_prior_run_selected(index: int) -> void:
	if index <= 0 or index - 1 >= _prior_runs.size():
		return
	var run: Dictionary = _prior_runs[index - 1]
	var result = run.get("result", {})
	if typeof(result) == TYPE_DICTIONARY and not result.is_empty():
		_apply_prior_run(run, result)
		return
	if _busy:
		_status_label.text = "Wait for the current request, then reselect the run."
		return
	_req_mode = ReqMode.PRIOR_RUN_ONE
	_set_busy(true)
	_status_label.text = "Loading prior run #%s…" % str(run.get("id", "?"))
	var err := _http.request("%s/analysis/counterfactual-runs/%s" % [
		_agent_base_url(),
		str(run.get("id", "")),
	])
	if err != OK:
		_set_busy(false)
		_status_label.text = "Prior-run request failed to start."


func _apply_prior_run(run: Dictionary, result: Dictionary) -> void:
	_last_cf_result = result
	run["result"] = result
	_render_cf_results(result, "")
	_rebuild_line_options()
	_select_cf_best_line_if_any()
	_status_label.text = "Loaded prior run #%s" % str(run.get("id", "?"))


func _on_run_failure() -> void:
	if _selected.is_empty() or _busy:
		return
	_req_mode = ReqMode.FAILURE_REPORT
	_set_busy(true)
	_status_label.text = "Running failure report…"
	_results_label.text = "Running failure report…"
	var body := _build_cf_request_body()
	body["with_counterfactual"] = _last_cf_result.is_empty()
	if not _last_cf_result.is_empty():
		body["counterfactual_result"] = _last_cf_result
		body["with_counterfactual"] = false
	var err := _http.request(
		_agent_base_url() + "/analysis/failure-report",
		["Content-Type: application/json"],
		HTTPClient.METHOD_POST,
		JSON.stringify(body),
	)
	if err != OK:
		_set_busy(false)
		_status_label.text = "Failure-report request failed to start."


func _on_request_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	var mode := _req_mode
	_req_mode = ReqMode.NONE
	_set_busy(false)

	if result != HTTPRequest.RESULT_SUCCESS:
		_status_label.add_theme_color_override("font_color", Color(0.90, 0.45, 0.45))
		if result == HTTPRequest.RESULT_TIMEOUT:
			_status_label.text = "Request timed out. Analysis can take a few minutes on a 4-turn horizon."
		else:
			_status_label.text = "HTTP transport error (%d). Is the agent running on :%d?" % [result, AGENT_PORT]
		return

	var text := body.get_string_from_utf8()
	var parsed = JSON.parse_string(text)

	match mode:
		ReqMode.HEALTH:
			if response_code == 200:
				_status_label.add_theme_color_override("font_color", Color(0.45, 0.85, 0.55))
				_status_label.text = "Agent online — loading decisions…"
				_load_decisions()
			else:
				_status_label.add_theme_color_override("font_color", Color(0.90, 0.45, 0.45))
				_status_label.text = "Agent unhealthy (HTTP %d)" % response_code
		ReqMode.LIST:
			if response_code != 200 or typeof(parsed) != TYPE_DICTIONARY:
				_status_label.add_theme_color_override("font_color", Color(0.90, 0.45, 0.45))
				_status_label.text = "List failed (HTTP %d)" % response_code
				return
			_populate_list(parsed.get("decisions", []))
			_status_label.add_theme_color_override("font_color", Color(0.55, 0.60, 0.72))
			_status_label.text = "Loaded %d decisions" % _listed.size()
		ReqMode.DETAIL:
			if response_code != 200 or typeof(parsed) != TYPE_DICTIONARY:
				_status_label.add_theme_color_override("font_color", Color(0.90, 0.45, 0.45))
				_status_label.text = "Detail failed (HTTP %d)" % response_code
				return
			_detail = parsed
			_last_cf_result = {}
			_show_detail()
			_rebuild_line_options()
			_status_label.text = "Decision loaded"
			if _pending_detail_then_board:
				_pending_detail_then_board = false
				_open_board_from_detail()
		ReqMode.CHECKPOINT:
			if response_code != 200 or typeof(parsed) != TYPE_DICTIONARY:
				_status_label.add_theme_color_override("font_color", Color(0.90, 0.45, 0.45))
				_status_label.text = "Checkpoint failed (HTTP %d)" % response_code
				return
			_merge_checkpoint_into_detail(parsed)
			_open_board_from_detail()
		ReqMode.PRIOR_RUN_ONE:
			if response_code != 200 or typeof(parsed) != TYPE_DICTIONARY:
				_status_label.add_theme_color_override("font_color", Color(0.90, 0.45, 0.45))
				_status_label.text = "Prior run failed (HTTP %d)" % response_code
				return
			var run_id := str(parsed.get("id", ""))
			var matched: Dictionary = {}
			for run in _prior_runs:
				if str(run.get("id", "")) == run_id:
					matched = run
					break
			var run_result = parsed.get("result", {})
			if typeof(run_result) != TYPE_DICTIONARY:
				run_result = {}
			_apply_prior_run(matched if not matched.is_empty() else parsed, run_result)
		ReqMode.PRIOR_RUNS:
			if response_code != 200 or typeof(parsed) != TYPE_DICTIONARY:
				_status_label.text = "Prior runs unavailable"
				_prior_runs.clear()
				_prior_runs_picker.clear()
				_prior_runs_picker.add_item("(none)")
				return
			_populate_prior_runs(parsed.get("runs", []))
		ReqMode.COUNTERFACTUAL:
			if response_code != 200 or typeof(parsed) != TYPE_DICTIONARY:
				_results_label.text = "Counterfactual failed (HTTP %d)\n%s" % [response_code, text]
				_status_label.add_theme_color_override("font_color", Color(0.90, 0.45, 0.45))
				_status_label.text = "Counterfactual failed"
				return
			_last_cf_result = parsed.get("result", {}) if typeof(parsed.get("result", {})) == TYPE_DICTIONARY else {}
			_render_cf_results(_last_cf_result, str(parsed.get("markdown", "")))
			_status_label.add_theme_color_override("font_color", Color(0.45, 0.85, 0.55))
			_status_label.text = "Analysis complete"
			_rebuild_line_options()
			_select_cf_best_line_if_any()
			_fetch_prior_runs()
		ReqMode.FAILURE_REPORT:
			if response_code != 200 or typeof(parsed) != TYPE_DICTIONARY:
				_results_label.text = "Failure report failed (HTTP %d)\n%s" % [response_code, text]
				_status_label.add_theme_color_override("font_color", Color(0.90, 0.45, 0.45))
				_status_label.text = "Failure report failed"
				return
			var cf = parsed.get("counterfactual", {})
			if typeof(cf) == TYPE_DICTIONARY and not cf.is_empty():
				_last_cf_result = cf
				_rebuild_line_options()
			_results_label.text = str(parsed.get("markdown", JSON.stringify(parsed, "\t")))
			_status_label.add_theme_color_override("font_color", Color(0.45, 0.85, 0.55))
			_status_label.text = "Failure report complete"
		_:
			pass


func _populate_prior_runs(runs: Array) -> void:
	_prior_runs = []
	_prior_runs_picker.clear()
	_prior_runs_picker.add_item("(select prior run)")
	for run in runs:
		if typeof(run) != TYPE_DICTIONARY:
			continue
		_prior_runs.append(run)
		var label := "#%s %s %s t+%s %s" % [
			str(run.get("id", "?")),
			str(run.get("run_kind", "?")),
			str(run.get("status", "?")),
			str(run.get("future_player_turns", 0)),
			str(run.get("timestamp", "")).substr(0, 19),
		]
		_prior_runs_picker.add_item(label)


func _render_cf_results(result: Dictionary, markdown: String) -> void:
	if result.is_empty():
		_results_label.text = markdown
		return
	var lines := PackedStringArray()
	var run_kind := str(result.get("run_kind", "same_turn"))
	lines.append("[b]status[/b]: %s   [b]run[/b]: %s" % [str(result.get("status")), run_kind])
	lines.append("[b]horizon[/b]: %s  future_turns=%s  truncated=%s (%s)" % [
		str(result.get("horizon")),
		str(result.get("future_player_turns", 0)),
		str(result.get("truncated")),
		str(result.get("stop_reason", "")),
	])
	lines.append("[b]policy[/b]: %s   [b]info[/b]: %s" % [
		str(result.get("opponent_policy")),
		str(result.get("information_mode")),
	])
	if result.get("readiness_warning"):
		lines.append("[color=#e09050]%s[/color]" % str(result.get("readiness_warning")))
	if result.get("error"):
		lines.append("[color=#e07070]error: %s[/color]" % str(result.get("error")))
		if result.get("detail"):
			lines.append(str(result.get("detail")))
	var tgt = result.get("target", {})
	if typeof(tgt) == TYPE_DICTIONARY and not tgt.is_empty():
		lines.append("[b]target[/b]: %s" % JSON.stringify(tgt))
	var hist = result.get("historical_outcome", {})
	if typeof(hist) == TYPE_DICTIONARY and not hist.is_empty():
		lines.append("[b]historical[/b]: %s" % JSON.stringify(hist))

	var tiers = result.get("outcome_tiers", {})
	if typeof(tiers) == TYPE_DICTIONARY and tiers.has("by_root"):
		lines.append("")
		lines.append("[b]Outcome tiers[/b]")
		var maximize := false
		if typeof(tgt) == TYPE_DICTIONARY:
			var tk := str(tgt.get("kind", ""))
			maximize = tk in ["max_score_after_turns", "max_score", "highest_score", "score_after_turns"]
		for row in tiers.get("by_root", []):
			if typeof(row) != TYPE_DICTIONARY:
				continue
			var badges := PackedStringArray()
			if row.get("possible"):
				badges.append("possible")
			if row.get("policy_likely"):
				badges.append("policy_likely")
			if row.get("robust"):
				badges.append("robust")
			var badge_s := ", ".join(badges) if not badges.is_empty() else "none"
			if maximize or str(row.get("objective", "")) == "maximize":
				var until_s := str(row.get("until_turn", tgt.get("until_turn", "?"))) if typeof(tgt) == TYPE_DICTIONARY else str(row.get("until_turn", "?"))
				var finished := int(row.get("success_count", 0))
				var total := int(row.get("path_count", 0))
				var policy_s := str(row.get("policy_value", "—"))
				if row.get("policy_value") == null:
					policy_s = "—"
				var best_s := str(row.get("possible_value", "—"))
				if row.get("possible_value") == null:
					best_s = "—"
				var rob_s := str(row.get("robust_value", "—"))
				if row.get("robust_value") == null:
					rob_s = "—"
				var horizon_note := "reached turn %s" % until_s
				if finished <= 0:
					var stop := _row_stop_reason(row)
					horizon_note = "did not finish turn %s (%s)" % [until_s, stop]
				var vs_played := ""
				if not badges.is_empty():
					vs_played = "  beats played: %s" % badge_s
				lines.append("- %s → %s  policy=%s (%s-%s)  best=%s  robust=%s  %d/%d leaves finished%s" % [
					str(row.get("root_line_id")),
					horizon_note,
					policy_s,
					str(row.get("policy_my_score", "?")),
					str(row.get("policy_opp_score", "?")),
					best_s,
					rob_s,
					finished,
					total,
					vs_played,
				])
			else:
				lines.append("- %s → [color=#9dcea0]%s[/color] (%s/%s)" % [
					str(row.get("root_line_id")),
					badge_s,
					str(row.get("success_count")),
					str(row.get("path_count")),
				])
		var improved = tiers.get("improved_roots", [])
		if typeof(improved) == TYPE_ARRAY and not improved.is_empty():
			var improved_ps := PackedStringArray()
			for x in improved:
				improved_ps.append(str(x))
			lines.append("[b]Improved vs played (policy):[/b] %s" % ", ".join(improved_ps))
		var possible_only = tiers.get("possible_only_roots", [])
		if typeof(possible_only) == TYPE_ARRAY and not possible_only.is_empty():
			var po := PackedStringArray()
			for x in possible_only:
				po.append(str(x))
			lines.append("[color=#e09050]Possible only if opponent plays a weaker line:[/color] %s" % ", ".join(po))
		if maximize:
			lines.append("[i]Until turn N = a leaf is scored only after game turn N has ended. policy/best/robust are blank when every branch stopped earlier (chain, time, or depth). \"none\" win badges are not used for this target.[/i]")
		else:
			lines.append("[i]policy PV = both seats' rank-1 search. possible = a win exists against a worse opponent reply — not a claim they would play that way.[/i]")
		for row in tiers.get("by_root", []):
			if typeof(row) != TYPE_DICTIONARY:
				continue
			var reps = row.get("representative_paths", {})
			if typeof(reps) != TYPE_DICTIONARY:
				continue
			for tier_name in ["policy_pv", "possible"]:
				var path = reps.get(tier_name)
				if typeof(path) != TYPE_DICTIONARY or path.is_empty():
					continue
				var hit := "lose vs rank-1 opp"
				if maximize:
					if path.get("objective_value") == null:
						hit = "stopped before turn %s (%s)" % [
							str(row.get("until_turn", tgt.get("until_turn", "?")) if typeof(tgt) == TYPE_DICTIONARY else row.get("until_turn", "?")),
							str(path.get("terminal_reason", "?")),
						]
					else:
						hit = "%s pts at turn %s" % [
							str(path.get("objective_value", path.get("my_score", "?"))),
							str(row.get("until_turn", "?")),
						]
				elif tier_name == "possible":
					hit = "win vs weak opp"
				elif row.get("policy_likely"):
					hit = "win vs rank-1 opp"
				lines.append("- %s/%s [%s] opponent: %s" % [
					str(row.get("root_line_id")),
					tier_name,
					hit,
					_summarize_opponent_segments(path, int(_detail.get("seat", 0))),
				])

	# Legacy same-turn packs
	var comparison = result.get("comparison", {})
	if typeof(comparison) == TYPE_DICTIONARY and comparison.has("packs"):
		lines.append("")
		lines.append("[b]Same-turn packs[/b]")
		for pack in comparison.get("packs", []):
			if typeof(pack) != TYPE_DICTIONARY:
				continue
			var off_m = pack.get("offline_hard_matches", [])
			var orig_m = pack.get("original_hard_matches", [])
			lines.append("- %s offline_hard=%s original_hard=%s" % [
				str(pack.get("pack_id")),
				str(off_m.size() if typeof(off_m) == TYPE_ARRAY else 0),
				str(orig_m.size() if typeof(orig_m) == TYPE_ARRAY else 0),
			])

	var assumptions = result.get("assumptions", {})
	if typeof(assumptions) == TYPE_DICTIONARY and assumptions.get("note"):
		lines.append("")
		lines.append("[i]%s[/i]" % str(assumptions.get("note")))

	var stats = result.get("search_stats", {})
	if typeof(stats) == TYPE_DICTIONARY and not stats.is_empty():
		lines.append("")
		lines.append("[b]stats[/b]: nodes=%s searches=%s elapsed_ms=%s" % [
			str(stats.get("nodes_explored", "?")),
			str(stats.get("searches", "?")),
			str(stats.get("elapsed_ms", "?")),
		])

	if result.has("same_turn_fallback") and typeof(result.get("same_turn_fallback")) == TYPE_DICTIONARY:
		var fb: Dictionary = result.get("same_turn_fallback")
		lines.append("")
		lines.append("[b]Same-turn fallback[/b]: status=%s ok=%s" % [
			str(fb.get("status")), str(fb.get("ok")),
		])

	if markdown != "" and run_kind == "same_turn":
		lines.append("")
		lines.append(markdown)
	_results_label.text = "\n".join(lines)


# ── List / detail ─────────────────────────────────────────────────────────────


func _populate_list(rows: Array) -> void:
	_listed = rows
	_decision_list.clear()
	for row in rows:
		if typeof(row) != TYPE_DICTIONARY:
			continue
		var action := str(row.get("action", "?"))
		var card := str(row.get("card_id", ""))
		var replay = row.get("replay_supported")
		var replay_mark := "✓" if replay == true else ("✗" if replay == false else "?")
		var label := "[%s] t%s/%s  %s%s  %s  %s" % [
			str(row.get("game_id", "")).substr(0, 12),
			str(row.get("turn", "")),
			str(row.get("decision_index", "")),
			action,
			(" " + card) if card != "" and card != "<null>" else "",
			replay_mark,
			str(row.get("timestamp", "")).substr(0, 19),
		]
		_decision_list.add_item(label)


func _on_decision_selected(index: int) -> void:
	if index < 0 or index >= _listed.size():
		return
	_selected = _listed[index]
	_sync_until_turn_bounds()
	_set_busy(false)
	_fetch_detail(false)
	_fetch_prior_runs()


func _show_detail() -> void:
	var ep: Dictionary = _detail.get("episodic", {}) if typeof(_detail.get("episodic", {})) == TYPE_DICTIONARY else {}
	var move: Dictionary = ep.get("move", {}) if typeof(ep.get("move", {})) == TYPE_DICTIONARY else {}
	var replay: Dictionary = _detail.get("replay", {}) if typeof(_detail.get("replay", {})) == TYPE_DICTIONARY else {}
	var cands: Array = _detail.get("candidates", [])
	var lines := PackedStringArray()
	lines.append("[b]%s[/b]  turn %s  idx %s  seat %s" % [
		str(_detail.get("game_id", "")),
		str(_detail.get("turn", "")),
		str(_detail.get("decision_index", "")),
		str(_detail.get("seat", 0)),
	])
	lines.append("action: %s   type: %s" % [
		str(move.get("action", "?")),
		str(ep.get("decision_type", "")),
	])
	lines.append("replay: %s  (%s)" % [
		str(replay.get("supported", "?")),
		str(replay.get("reason", "")),
	])
	lines.append("snapshot_status: %s   hash: %s" % [
		str(_detail.get("snapshot_status", "")),
		str(_detail.get("root_state_hash", "")),
	])
	lines.append("candidates: %d" % cands.size())
	var reasoning := str(ep.get("reasoning", ""))
	if reasoning != "":
		lines.append("")
		lines.append("[i]%s[/i]" % reasoning.substr(0, 600))
	_detail_label.text = "\n".join(lines)


# ── Board / lines ─────────────────────────────────────────────────────────────


func _on_open_board() -> void:
	if _selected.is_empty() or _busy:
		return
	if not _detail.is_empty() \
			and str(_detail.get("game_id", "")) == str(_selected.get("game_id", "")) \
			and int(_detail.get("turn", -1)) == int(_selected.get("turn", -2)) \
			and int(_detail.get("decision_index", -1)) == int(_selected.get("decision_index", -2)):
		if not _analysis_state_from_detail().is_empty():
			_open_board_from_detail()
		else:
			_fetch_checkpoint()
	else:
		_fetch_detail(true)


func _merge_checkpoint_into_detail(payload: Dictionary) -> void:
	if _detail.is_empty():
		_detail = {
			"game_id": payload.get("game_id"),
			"turn": payload.get("turn"),
			"decision_index": payload.get("decision_index"),
			"seat": payload.get("seat", 0),
			"candidates": [],
		}
	_detail["seat"] = payload.get("seat", _detail.get("seat", 0))
	_detail["root_state_hash"] = payload.get("root_state_hash", _detail.get("root_state_hash"))
	_detail["replay"] = payload.get("replay", _detail.get("replay"))
	_detail["snapshot_status"] = payload.get("snapshot_status", _detail.get("snapshot_status"))
	var snap: Dictionary = _detail.get("snapshot", {}) if typeof(_detail.get("snapshot", {})) == TYPE_DICTIONARY else {}
	snap["analysis_state"] = payload.get("analysis_state")
	snap["analysis_state_json"] = null
	_detail["snapshot"] = snap


func _analysis_state_from_detail() -> Dictionary:
	var snap = _detail.get("snapshot")
	if typeof(snap) != TYPE_DICTIONARY:
		return {}
	var state = snap.get("analysis_state")
	if typeof(state) == TYPE_DICTIONARY:
		return state
	var raw = snap.get("analysis_state_json")
	if typeof(raw) == TYPE_DICTIONARY:
		return raw
	if typeof(raw) == TYPE_STRING and str(raw) != "":
		var parsed = JSON.parse_string(str(raw))
		if typeof(parsed) == TYPE_DICTIONARY:
			return parsed
	return {}


func _open_board_from_detail() -> void:
	var payload := _analysis_state_from_detail()
	if payload.is_empty():
		_status_label.add_theme_color_override("font_color", Color(0.90, 0.45, 0.45))
		_status_label.text = "No analysis_state on this decision"
		return
	var restored: Dictionary = AnalysisStateCodecScript.restore_state(payload)
	if not bool(restored.get("ok", false)):
		_status_label.add_theme_color_override("font_color", Color(0.90, 0.45, 0.45))
		_status_label.text = "Restore failed: %s" % str(restored.get("error", "?"))
		return
	_root_gs = restored["gs"] as GameState
	var seat := int(_detail.get("seat", 0))
	var expected := str(_detail.get("root_state_hash", ""))
	if expected != "":
		var got := AnalysisStateCodecScript.root_hash(_root_gs, seat)
		if got != expected:
			_status_label.add_theme_color_override("font_color", Color(0.95, 0.75, 0.35))
			_status_label.text = "Hash mismatch (viewing anyway)"
		else:
			_status_label.add_theme_color_override("font_color", Color(0.45, 0.85, 0.55))
			_status_label.text = "Checkpoint restored"
	else:
		_status_label.text = "Checkpoint restored"

	_rebuild_line_options()
	if not _last_cf_result.is_empty() and _select_cf_best_line_if_any():
		return
	if _line_picker.item_count > 0:
		_line_picker.select(0)
	_timeline.build_root_only(_root_gs, seat)
	_sync_board_from_timeline()


func _rebuild_line_options() -> void:
	_line_options.clear()
	_line_picker.clear()
	_line_options.append({
		"id": "root",
		"label": "Checkpoint (before this decision)",
		"moves": [],
		"source": "root",
	})
	_line_picker.add_item("Checkpoint (before this decision)")
	var cands: Array = _detail.get("candidates", []) if typeof(_detail.get("candidates", [])) == TYPE_ARRAY else []
	for c in cands:
		if typeof(c) != TYPE_DICTIONARY:
			continue
		var moves: Array = c.get("moves", []) if typeof(c.get("moves", [])) == TYPE_ARRAY else []
		var lid := str(c.get("line_id", "?"))
		var chosen := bool(c.get("chosen", false))
		var score = c.get("score", "")
		var label := "%s%s  score=%s  (%d moves)" % [
			"★ Played: " if chosen else "Alt: ",
			lid,
			str(score),
			moves.size(),
		]
		_line_options.append({"id": lid, "label": label, "moves": moves, "source": "candidate"})
		_line_picker.add_item(label)

	if _last_cf_result.is_empty():
		return

	var seen_keys: Dictionary = {}
	for opt in _line_options:
		seen_keys[_moves_key(opt.get("moves", []))] = true

	# Outcome-rollout paths (schema v2)
	var tiers = _last_cf_result.get("outcome_tiers", {})
	if typeof(tiers) == TYPE_DICTIONARY:
		var by_root = tiers.get("by_root", [])
		if typeof(by_root) == TYPE_ARRAY:
			for row in by_root:
				if typeof(row) != TYPE_DICTIONARY:
					continue
				var reps = row.get("representative_paths", {})
				if typeof(reps) != TYPE_DICTIONARY:
					continue
				var opp_groups := int(row.get("opponent_groups", 0))
				var maximize := _is_maximize_result()
				var tiers_to_show: Array = ["policy_pv"]
				if not maximize:
					tiers_to_show.append("policy_likely")
				# Robust is only a distinct claim when ≥2 opponent replies were kept.
				if opp_groups >= 2:
					tiers_to_show.append("robust")
				tiers_to_show.append("possible")
				for tier_name in tiers_to_show:
					var path = reps.get(tier_name)
					if typeof(path) != TYPE_DICTIONARY or path.is_empty():
						continue
					var moves2 = path.get("moves", [])
					if typeof(moves2) != TYPE_ARRAY:
						continue
					var key := _moves_key(moves2)
					if seen_keys.has(key):
						continue
					seen_keys[key] = true
					var lid2 := "%s/%s" % [str(row.get("root_line_id")), tier_name]
					var finished := path.get("objective_value") != null if maximize else true
					var obj = path.get("objective_value", path.get("score", ""))
					var label2: String
					if maximize and not finished:
						label2 = "Rollout [%s] %s  truncated (%s)  (%d moves)" % [
							_tier_label(tier_name),
							str(row.get("root_line_id")),
							str(path.get("terminal_reason", "early_stop")),
							moves2.size(),
						]
					else:
						label2 = "Rollout [%s] %s  %s  (%d moves)" % [
							_tier_label(tier_name),
							str(row.get("root_line_id")),
							str(obj),
							moves2.size(),
						]
					_line_options.append({
						"id": lid2,
						"label": label2,
						"moves": moves2,
						"source": "rollout",
						"path": path,
						"tier": tier_name,
						"root_line_id": str(row.get("root_line_id")),
						"policy_value": row.get("policy_value"),
						"possible_value": row.get("possible_value"),
						"objective_value": obj,
					})
					_line_picker.add_item(label2)

	# Raw candidate_lines are every rollout leaf (incomplete chains, pruned
	# branches, duplicates). Representative paths above are the useful ones.

	# Legacy same-turn CF offline lines
	var comparison = _last_cf_result.get("comparison", {})
	if typeof(comparison) == TYPE_DICTIONARY:
		_maybe_add_cf_line(comparison.get("played"), "CF played", seen_keys)
		for pack in comparison.get("packs", []):
			if typeof(pack) != TYPE_DICTIONARY:
				continue
			var pack_id := str(pack.get("pack_id", "pack"))
			var matches = pack.get("offline_hard_matches", [])
			if typeof(matches) != TYPE_ARRAY or matches.is_empty():
				continue
			_maybe_add_cf_line(matches[0], "CF best [%s]" % pack_id, seen_keys)

	var cf_cands = _last_cf_result.get("candidate_lines", [])
	if typeof(cf_cands) == TYPE_ARRAY and str(_last_cf_result.get("run_kind", "")) == "same_turn":
		var ci := 0
		for line in cf_cands:
			if typeof(line) != TYPE_DICTIONARY:
				continue
			var moves = line.get("canonical_moves", line.get("moves", []))
			if typeof(moves) != TYPE_ARRAY or moves.is_empty():
				continue
			var key := _moves_key(moves)
			if seen_keys.has(key):
				continue
			seen_keys[key] = true
			var lid := str(line.get("line_id", "offline-%d" % ci))
			var label := "CF offline: %s (%d moves)" % [lid, moves.size()]
			_line_options.append({"id": lid, "label": label, "moves": moves, "source": "cf"})
			_line_picker.add_item(label)
			ci += 1


func _is_maximize_result() -> bool:
	var tgt = _last_cf_result.get("target", {})
	if typeof(tgt) != TYPE_DICTIONARY:
		return false
	return str(tgt.get("kind", "")) in [
		"max_score_after_turns", "max_score", "highest_score", "score_after_turns",
	]


func _option_numeric(opt: Dictionary, key: String) -> float:
	var v = opt.get(key, null)
	if v == null or str(v) == "" or str(v) == "<null>":
		return -INF
	return float(v)


func _best_rollout_line_index() -> int:
	# Maximize: policy PV of the root with the best completed policy_value.
	# Win/control: policy_likely, then policy PV, then robust, then possible.
	if _is_maximize_result():
		var best_i := -1
		var best_v := -INF
		for i in range(_line_options.size()):
			var opt: Dictionary = _line_options[i]
			if str(opt.get("source", "")) != "rollout":
				continue
			if str(opt.get("tier", "")) != "policy_pv":
				continue
			var v := _option_numeric(opt, "policy_value")
			if v == -INF:
				v = _option_numeric(opt, "objective_value")
			if v > best_v:
				best_v = v
				best_i = i
		if best_i >= 0:
			return best_i
		best_i = -1
		best_v = -INF
		for i in range(_line_options.size()):
			var opt2: Dictionary = _line_options[i]
			if str(opt2.get("source", "")) != "rollout":
				continue
			if str(opt2.get("tier", "")) != "possible":
				continue
			var v2 := _option_numeric(opt2, "possible_value")
			if v2 == -INF:
				v2 = _option_numeric(opt2, "objective_value")
			if v2 > best_v:
				best_v = v2
				best_i = i
		return best_i
	for want in ["policy_likely", "policy_pv", "robust", "possible"]:
		for i in range(_line_options.size()):
			if str(_line_options[i].get("source", "")) == "rollout" \
					and str(_line_options[i].get("tier", "")) == want:
				return i
	return -1


func _select_cf_best_line_if_any() -> bool:
	var idx := _best_rollout_line_index()
	if idx < 0:
		for i in range(_line_options.size()):
			if str(_line_options[i].get("source", "")) == "cf" \
					and str(_line_options[i].get("label", "")).begins_with("CF best"):
				idx = i
				break
	if idx < 0:
		for i in range(_line_options.size()):
			if str(_line_options[i].get("source", "")) in ["cf", "rollout"]:
				idx = i
				break
	if idx < 0:
		return false
	_line_picker.select(idx)
	if _root_gs != null:
		_on_line_selected(idx)
		return true
	return false


func _on_line_selected(index: int) -> void:
	if _root_gs == null:
		return
	if index < 0 or index >= _line_options.size():
		_timeline.build_root_only(_root_gs, int(_detail.get("seat", 0)))
		_sync_board_from_timeline()
		return
	var opt: Dictionary = _line_options[index]
	var seat := int(_detail.get("seat", 0))
	var built: Dictionary
	if str(opt.get("source", "")) == "root":
		built = _timeline.build_root_only(_root_gs, seat)
	elif opt.has("path") and typeof(opt.get("path")) == TYPE_DICTIONARY:
		built = _timeline.build_from_path(_root_gs, opt.get("path"), seat)
	else:
		var moves: Array = opt.get("moves", [])
		if typeof(moves) != TYPE_ARRAY or moves.is_empty():
			built = _timeline.build_root_only(_root_gs, seat)
		else:
			built = _timeline.build_from_line(_root_gs, moves, seat, str(opt.get("id", "")))
	if not bool(built.get("ok", false)):
		_status_label.add_theme_color_override("font_color", Color(0.90, 0.45, 0.45))
		_status_label.text = "Timeline build failed: %s" % str(built.get("error", "?"))
	# Rollout/CF lines are scored at the leaf. Show that board, not the root ply.
	if str(opt.get("source", "")) in ["rollout", "cf"] and _timeline.size() > 1:
		_timeline.set_cursor(_timeline.size() - 1)
	_sync_board_from_timeline()


func _sync_board_from_timeline() -> void:
	_move_list.clear()
	for label in _timeline.move_labels():
		_move_list.add_item(label)
	_refresh_step_ui()


func _refresh_step_ui() -> void:
	if _timeline.is_empty():
		_step_label.text = "Step —"
		return
	_step_label.text = "Step %d / %d" % [_timeline.cursor, _timeline.size() - 1]
	var gs := _timeline.current_gs()
	if gs != null and _board_view != null:
		_board_view.refresh(gs)
	if _timeline.cursor >= 0 and _timeline.cursor < _move_list.item_count:
		_move_list.select(_timeline.cursor)


func _on_step_prev() -> void:
	if _timeline.step_prev():
		_refresh_step_ui()


func _on_step_next() -> void:
	if _timeline.step_next():
		_refresh_step_ui()


func _on_move_jumped(index: int) -> void:
	if _timeline.set_cursor(index):
		_refresh_step_ui()
	else:
		# Same cursor — still refresh selection highlight
		_refresh_step_ui()


func _row_stop_reason(row: Dictionary) -> String:
	var reps = row.get("representative_paths", {})
	if typeof(reps) != TYPE_DICTIONARY:
		return "no completed leaf"
	for name in ["policy_pv", "possible", "robust", "policy_likely"]:
		var path = reps.get(name)
		if typeof(path) == TYPE_DICTIONARY and str(path.get("terminal_reason", "")) != "":
			return str(path.get("terminal_reason"))
	return "no completed leaf"


func _tier_label(tier_name: String) -> String:
	match tier_name:
		"policy_pv":
			return "policy PV"
		"policy_likely":
			return "policy win"
		"possible":
			return "best / possible (weak opp)"
		"robust":
			return "robust"
		_:
			return tier_name


func _summarize_opponent_segments(path: Dictionary, analyzed_seat: int) -> String:
	var parts := PackedStringArray()
	for seg in path.get("path_segments", []):
		if typeof(seg) != TYPE_DICTIONARY:
			continue
		if int(seg.get("seat", analyzed_seat)) == analyzed_seat:
			continue
		var actions := PackedStringArray()
		for m in seg.get("moves", []):
			var s := str(m)
			if s == "" or s == "pass" or s.begins_with("choose "):
				continue
			actions.append(s)
		if actions.is_empty():
			parts.append("S%s skip/end-turn" % str(seg.get("seat", "?")))
		else:
			parts.append("S%s %s" % [str(seg.get("seat", "?")), ", ".join(actions)])
	if parts.is_empty():
		return "(no opponent segment)"
	return " | ".join(parts)


func _on_back_menu() -> void:
	get_tree().change_scene_to_file("res://Scenes/MainMenu.tscn")
