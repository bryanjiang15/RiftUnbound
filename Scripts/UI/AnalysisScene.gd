extends Control

# Post-game Analysis UI: browse agent_memory.db decisions via the AI agent
# (localhost:8765), restore checkpoints onto BoardView, step ply-by-ply through
# played / candidate / counterfactual lines, and run CF / failure-report analysis.

const AGENT_PORT := 8765
const AnalysisStateCodecScript = preload("res://Scripts/AI/AnalysisStateCodec.gd")
const AnalysisTimelineScript = preload("res://Scripts/UI/AnalysisTimeline.gd")
const BoardViewScript = preload("res://Scripts/UI/BoardView.gd")

enum ReqMode { NONE, LIST, DETAIL, COUNTERFACTUAL, FAILURE_REPORT, HEALTH }

var _http: HTTPRequest
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

# Board / stepping
var _board_view: BoardView
var _line_picker: OptionButton
var _move_list: ItemList
var _step_label: Label
var _prev_btn: Button
var _next_btn: Button
var _board_panel: Control

var _selected: Dictionary = {}
var _detail: Dictionary = {}
var _root_gs: GameState = null
var _timeline: AnalysisTimeline = null
var _line_options: Array = []  # [{id, label, moves}]
var _last_cf_result: Dictionary = {}
var _pending_detail_then_board: bool = false


func _ready() -> void:
	_timeline = AnalysisTimelineScript.new()
	_http = HTTPRequest.new()
	_http.timeout = 600.0  # CF can spawn headless Godot
	add_child(_http)
	_http.request_completed.connect(_on_request_completed)
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

	var mid := HSplitContainer.new()
	mid.size_flags_vertical = Control.SIZE_EXPAND_FILL
	mid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	mid.split_offset = 420
	root.add_child(mid)

	mid.add_child(_build_list_panel())
	mid.add_child(_build_detail_panel())

	_board_panel = _build_board_panel()
	_board_panel.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_board_panel.custom_minimum_size = Vector2(0, 320)
	root.add_child(_board_panel)


func _build_header() -> Control:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 16)

	var title := Label.new()
	title.text = "Post-Game Analysis"
	title.add_theme_font_size_override("font_size", 26)
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
	vbox.add_theme_constant_override("separation", 8)
	panel.add_child(vbox)

	var lbl := Label.new()
	lbl.text = "Detail"
	lbl.add_theme_font_size_override("font_size", 16)
	lbl.add_theme_color_override("font_color", Color(0.75, 0.78, 0.88))
	vbox.add_child(lbl)

	_detail_label = RichTextLabel.new()
	_detail_label.bbcode_enabled = true
	_detail_label.fit_content = false
	_detail_label.scroll_active = true
	_detail_label.custom_minimum_size = Vector2(0, 140)
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
	_run_cf_btn.text = "Run Counterfactual"
	_run_cf_btn.pressed.connect(_on_run_cf)
	actions.add_child(_run_cf_btn)

	_run_fail_btn = Button.new()
	_run_fail_btn.text = "Failure Report"
	_run_fail_btn.pressed.connect(_on_run_failure)
	actions.add_child(_run_fail_btn)

	var res_lbl := Label.new()
	res_lbl.text = "Analysis Results"
	res_lbl.add_theme_font_size_override("font_size", 14)
	res_lbl.add_theme_color_override("font_color", Color(0.70, 0.74, 0.85))
	vbox.add_child(res_lbl)

	_results_label = RichTextLabel.new()
	_results_label.bbcode_enabled = false
	_results_label.fit_content = false
	_results_label.scroll_active = true
	_results_label.custom_minimum_size = Vector2(0, 120)
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
	_board_view.custom_minimum_size = Vector2(400, 280)
	board_row.add_child(_board_view)

	var moves_wrap := VBoxContainer.new()
	moves_wrap.custom_minimum_size = Vector2(220, 0)
	board_row.add_child(moves_wrap)

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
	var url := "%s/analysis/decision?game_id=%s&turn=%d&decision_index=%d" % [
		_agent_base_url(),
		str(_selected.get("game_id", "")).uri_encode(),
		int(_selected.get("turn", 0)),
		int(_selected.get("decision_index", 0)),
	]
	var err := _http.request(url)
	if err != OK:
		_set_busy(false)
		_status_label.text = "Detail request failed to start."


func _on_run_cf() -> void:
	if _selected.is_empty() or _busy:
		return
	_req_mode = ReqMode.COUNTERFACTUAL
	_set_busy(true)
	_status_label.text = "Running counterfactual (may take a while)…"
	_results_label.text = "Running counterfactual…"
	var body := {
		"game_id": str(_selected.get("game_id", "")),
		"turn": int(_selected.get("turn", 0)),
		"decision_index": int(_selected.get("decision_index", 0)),
		"persist": true,
	}
	var err := _http.request(
		_agent_base_url() + "/analysis/counterfactual",
		["Content-Type: application/json"],
		HTTPClient.METHOD_POST,
		JSON.stringify(body),
	)
	if err != OK:
		_set_busy(false)
		_status_label.text = "CF request failed to start."


func _on_run_failure() -> void:
	if _selected.is_empty() or _busy:
		return
	_req_mode = ReqMode.FAILURE_REPORT
	_set_busy(true)
	_status_label.text = "Running failure report…"
	_results_label.text = "Running failure report…"
	var body := {
		"game_id": str(_selected.get("game_id", "")),
		"turn": int(_selected.get("turn", 0)),
		"decision_index": int(_selected.get("decision_index", 0)),
		"persist": true,
		"with_counterfactual": _last_cf_result.is_empty(),
	}
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
		ReqMode.COUNTERFACTUAL:
			if response_code != 200 or typeof(parsed) != TYPE_DICTIONARY:
				_results_label.text = "Counterfactual failed (HTTP %d)\n%s" % [response_code, text]
				_status_label.add_theme_color_override("font_color", Color(0.90, 0.45, 0.45))
				_status_label.text = "Counterfactual failed"
				return
			_last_cf_result = parsed.get("result", {}) if typeof(parsed.get("result", {})) == TYPE_DICTIONARY else {}
			_results_label.text = str(parsed.get("markdown", JSON.stringify(parsed, "\t")))
			_status_label.add_theme_color_override("font_color", Color(0.45, 0.85, 0.55))
			_status_label.text = "Counterfactual complete"
			_rebuild_line_options()
			_select_cf_best_line_if_any()
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
	_set_busy(false)
	_fetch_detail(false)


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
	if _selected.is_empty():
		return
	if not _detail.is_empty() \
			and str(_detail.get("game_id", "")) == str(_selected.get("game_id", "")) \
			and int(_detail.get("turn", -1)) == int(_selected.get("turn", -2)) \
			and int(_detail.get("decision_index", -1)) == int(_selected.get("decision_index", -2)):
		_open_board_from_detail()
	else:
		_fetch_detail(true)


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
	if _line_picker.item_count > 0:
		_line_picker.select(0)
		_on_line_selected(0)
	else:
		_timeline.build_root_only(_root_gs, seat)
		_sync_board_from_timeline()


func _rebuild_line_options() -> void:
	_line_options.clear()
	_line_picker.clear()
	var cands: Array = _detail.get("candidates", []) if typeof(_detail.get("candidates", [])) == TYPE_ARRAY else []
	for c in cands:
		if typeof(c) != TYPE_DICTIONARY:
			continue
		var moves: Array = c.get("moves", []) if typeof(c.get("moves", [])) == TYPE_ARRAY else []
		var lid := str(c.get("line_id", "?"))
		var chosen := bool(c.get("chosen", false))
		var score = c.get("score", "")
		var label := "%s%s  score=%s  (%d moves)" % [
			"★ " if chosen else "",
			lid,
			str(score),
			moves.size(),
		]
		_line_options.append({"id": lid, "label": label, "moves": moves, "source": "candidate"})
		_line_picker.add_item(label)

	# CF offline lines: top-level candidate_lines + pack hard-matches + played
	if not _last_cf_result.is_empty():
		var seen_keys: Dictionary = {}
		for opt in _line_options:
			seen_keys[_moves_key(opt.get("moves", []))] = true

		var cf_cands = _last_cf_result.get("candidate_lines", [])
		if typeof(cf_cands) == TYPE_ARRAY:
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


func _select_cf_best_line_if_any() -> void:
	for i in range(_line_options.size()):
		if str(_line_options[i].get("source", "")) == "cf" \
				and str(_line_options[i].get("label", "")).begins_with("CF best"):
			_line_picker.select(i)
			if _root_gs != null:
				_on_line_selected(i)
			return
	# Fall back to first CF offline line
	for i in range(_line_options.size()):
		if str(_line_options[i].get("source", "")) == "cf":
			_line_picker.select(i)
			if _root_gs != null:
				_on_line_selected(i)
			return


func _on_line_selected(index: int) -> void:
	if _root_gs == null:
		return
	if index < 0 or index >= _line_options.size():
		_timeline.build_root_only(_root_gs, int(_detail.get("seat", 0)))
		_sync_board_from_timeline()
		return
	var opt: Dictionary = _line_options[index]
	var moves: Array = opt.get("moves", [])
	var seat := int(_detail.get("seat", 0))
	var built: Dictionary = _timeline.build_from_line(_root_gs, moves, seat, str(opt.get("id", "")))
	if not bool(built.get("ok", false)):
		_status_label.add_theme_color_override("font_color", Color(0.90, 0.45, 0.45))
		_status_label.text = "Timeline build failed: %s" % str(built.get("error", "?"))
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


func _on_back_menu() -> void:
	get_tree().change_scene_to_file("res://Scenes/MainMenu.tscn")
