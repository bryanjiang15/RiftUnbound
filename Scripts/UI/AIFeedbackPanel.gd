class_name AIFeedbackPanel
extends Control

# Post-game human evaluation form for the AI opponent.  Shown only when the
# "Enable Human AI Evaluation" toggle was set in the Main Menu and the match was
# Player vs AI.  Collects rubric scores (1-5), optional tags, and a free-text
# note, then POSTs them to the Python agent's /human_feedback endpoint.
#
# Usage:
#   var panel := AIFeedbackPanel.new()
#   add_child(panel)
#   panel.show_for_game(game_id)

signal closed

const AGENT_PORT := 8765

# Rubric criteria: key -> display label.
const CRITERIA := {
	"strategic": "Strategic coherence",
	"tactical": "Tactical correctness",
	"resource": "Resource efficiency",
	"rules": "Rules understanding",
	"overall": "Overall play",
}

const TAG_OPTIONS := [
	"missed lethal", "bad trade", "good defense",
	"wasted resources", "misplayed rules", "strong line",
]

var _game_id: String = ""
var _score_pickers: Dictionary = {}   # criterion key -> OptionButton
var _tag_checks: Dictionary = {}      # tag -> CheckBox
var _note_edit: TextEdit
var _http: HTTPRequest
var _status_label: Label


func _ready() -> void:
	_http = HTTPRequest.new()
	add_child(_http)
	_http.request_completed.connect(_on_request_completed)


func show_for_game(game_id: String) -> void:
	_game_id = game_id
	_build_ui()
	visible = true


func _agent_base_url() -> String:
	var host := "127.0.0.1" if OS.get_name() == "Windows" else "localhost"
	return "http://%s:%d" % [host, AGENT_PORT]


func _build_ui() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

	var dim := ColorRect.new()
	dim.color = Color(0.0, 0.0, 0.0, 0.6)
	dim.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(dim)

	var center := CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(center)

	var panel := PanelContainer.new()
	var sb := StyleBoxFlat.new()
	sb.bg_color = Color(0.08, 0.08, 0.12, 0.98)
	sb.border_color = Color(0.45, 0.45, 0.60)
	sb.set_border_width_all(2)
	sb.set_corner_radius_all(8)
	sb.set_content_margin_all(24)
	panel.add_theme_stylebox_override("panel", sb)
	center.add_child(panel)

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 14)
	vbox.custom_minimum_size = Vector2(480, 0)
	panel.add_child(vbox)

	var title := Label.new()
	title.text = "Rate the AI's Play"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 26)
	title.add_theme_color_override("font_color", Color(0.85, 0.72, 0.35))
	vbox.add_child(title)

	var hint := Label.new()
	hint.text = "Score each from 1 (poor) to 5 (excellent)."
	hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	hint.add_theme_font_size_override("font_size", 14)
	hint.add_theme_color_override("font_color", Color(0.58, 0.63, 0.76))
	vbox.add_child(hint)

	for key in CRITERIA:
		vbox.add_child(_make_score_row(key, str(CRITERIA[key])))

	var tags_label := Label.new()
	tags_label.text = "Tags (optional)"
	tags_label.add_theme_font_size_override("font_size", 15)
	tags_label.add_theme_color_override("font_color", Color(0.70, 0.74, 0.85))
	vbox.add_child(tags_label)

	var tag_grid := GridContainer.new()
	tag_grid.columns = 3
	tag_grid.add_theme_constant_override("h_separation", 14)
	for tag in TAG_OPTIONS:
		var cb := CheckBox.new()
		cb.text = tag
		cb.add_theme_font_size_override("font_size", 13)
		cb.add_theme_color_override("font_color", Color(0.62, 0.66, 0.78))
		_tag_checks[tag] = cb
		tag_grid.add_child(cb)
	vbox.add_child(tag_grid)

	var note_label := Label.new()
	note_label.text = "Notes (optional)"
	note_label.add_theme_font_size_override("font_size", 15)
	note_label.add_theme_color_override("font_color", Color(0.70, 0.74, 0.85))
	vbox.add_child(note_label)

	_note_edit = TextEdit.new()
	_note_edit.custom_minimum_size = Vector2(0, 70)
	_note_edit.placeholder_text = "What did the AI do well or badly?"
	vbox.add_child(_note_edit)

	_status_label = Label.new()
	_status_label.text = ""
	_status_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_status_label.add_theme_font_size_override("font_size", 13)
	_status_label.add_theme_color_override("font_color", Color(0.55, 0.75, 0.55))
	vbox.add_child(_status_label)

	var buttons := HBoxContainer.new()
	buttons.alignment = BoxContainer.ALIGNMENT_CENTER
	buttons.add_theme_constant_override("separation", 16)

	var submit_btn := Button.new()
	submit_btn.text = "Submit"
	submit_btn.custom_minimum_size = Vector2(160, 44)
	submit_btn.pressed.connect(_on_submit_pressed)
	buttons.add_child(submit_btn)

	var skip_btn := Button.new()
	skip_btn.text = "Skip"
	skip_btn.custom_minimum_size = Vector2(160, 44)
	skip_btn.pressed.connect(_on_skip_pressed)
	buttons.add_child(skip_btn)

	vbox.add_child(buttons)


func _make_score_row(key: String, label_text: String) -> HBoxContainer:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)

	var label := Label.new()
	label.text = label_text
	label.custom_minimum_size = Vector2(220, 0)
	label.add_theme_font_size_override("font_size", 15)
	label.add_theme_color_override("font_color", Color(0.72, 0.76, 0.86))
	row.add_child(label)

	var picker := OptionButton.new()
	picker.custom_minimum_size = Vector2(120, 34)
	picker.add_item("—", 0)        # unscored
	for i in range(1, 6):
		picker.add_item(str(i), i)
	picker.select(0)
	_score_pickers[key] = picker
	row.add_child(picker)

	return row


func _on_submit_pressed() -> void:
	var body := {"game_id": _game_id, "scope": "game"}

	for key in _score_pickers:
		var picker: OptionButton = _score_pickers[key]
		var v := picker.get_selected_id()
		if v >= 1:
			body[key] = v

	var tags: Array = []
	for tag in _tag_checks:
		if _tag_checks[tag].button_pressed:
			tags.append(tag)
	if not tags.is_empty():
		body["tags"] = tags

	var note := _note_edit.text.strip_edges()
	if note != "":
		body["note"] = note

	var url := _agent_base_url() + "/human_feedback"
	var err := _http.request(url, ["Content-Type: application/json"],
		HTTPClient.METHOD_POST, JSON.stringify(body))
	if err != OK:
		_status_label.add_theme_color_override("font_color", Color(0.85, 0.45, 0.45))
		_status_label.text = "Could not reach the agent service."
		return
	_status_label.text = "Submitting…"


func _on_request_completed(result: int, response_code: int, _headers: PackedStringArray, _body: PackedByteArray) -> void:
	if result == HTTPRequest.RESULT_SUCCESS and response_code == 200:
		_close()
	else:
		_status_label.add_theme_color_override("font_color", Color(0.85, 0.45, 0.45))
		_status_label.text = "Submit failed (code %d). You can Skip." % response_code


func _on_skip_pressed() -> void:
	_close()


func _close() -> void:
	closed.emit()
	visible = false
	queue_free()
