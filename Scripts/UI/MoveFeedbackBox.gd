class_name MoveFeedbackBox
extends PanelContainer

# Small always-on-screen widget that lets a human rate each AI move live.
# After every accepted AI move it "lights up" (border glows, buttons enable);
# the player may click Like / Neutral / Dislike, or simply ignore it. Ignoring
# records nothing — that is how an ignored move is distinguished from an
# explicit "neutral" rating.
#
# Usage (from GameScene):
#   var box := MoveFeedbackBox.new()
#   box.configure(game_id_provider)   # Callable returning the current game_id
#   add_child(box)
#   ai_player.ai_move_completed.connect(box.on_ai_move)

const AGENT_PORT := 8765

# sentiment key -> [label, idle color, active color]
const BUTTONS := {
	"like":    ["Like",    Color(0.35, 0.75, 0.40)],
	"neutral": ["Neutral", Color(0.70, 0.70, 0.45)],
	"dislike": ["Dislike", Color(0.80, 0.40, 0.40)],
}

var _game_id_provider: Callable = Callable()
var _http: HTTPRequest
var _title: Label
var _move_label: Label
var _status: Label
var _buttons: Dictionary = {}        # sentiment -> Button
var _border: StyleBoxFlat

var _pending_turn: int = -1
var _pending_seq: int = -1
var _pending_desc: String = ""
var _armed: bool = false             # a move is awaiting rating
var _glow: float = 0.0


func configure(game_id_provider: Callable) -> void:
	_game_id_provider = game_id_provider


func _agent_base_url() -> String:
	var host := "127.0.0.1" if OS.get_name() == "Windows" else "localhost"
	return "http://%s:%d" % [host, AGENT_PORT]


func _ready() -> void:
	custom_minimum_size = Vector2(210, 0)
	mouse_filter = Control.MOUSE_FILTER_STOP

	_border = StyleBoxFlat.new()
	_border.bg_color = Color(0.09, 0.09, 0.13, 0.95)
	_border.border_color = Color(0.30, 0.32, 0.42)
	_border.set_border_width_all(2)
	_border.set_corner_radius_all(8)
	_border.set_content_margin_all(10)
	add_theme_stylebox_override("panel", _border)

	_http = HTTPRequest.new()
	add_child(_http)
	_http.request_completed.connect(_on_request_completed)

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 6)
	add_child(vbox)

	_title = Label.new()
	_title.text = "Rate the AI's move"
	_title.add_theme_font_size_override("font_size", 14)
	_title.add_theme_color_override("font_color", Color(0.78, 0.80, 0.90))
	vbox.add_child(_title)

	_move_label = Label.new()
	_move_label.text = "(waiting for AI...)"
	_move_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_move_label.custom_minimum_size = Vector2(190, 0)
	_move_label.add_theme_font_size_override("font_size", 12)
	_move_label.add_theme_color_override("font_color", Color(0.60, 0.64, 0.76))
	vbox.add_child(_move_label)

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 6)
	row.alignment = BoxContainer.ALIGNMENT_CENTER
	for key in BUTTONS:
		var btn := Button.new()
		btn.text = str(BUTTONS[key][0])
		btn.custom_minimum_size = Vector2(60, 34)
		btn.disabled = true
		btn.pressed.connect(_on_sentiment.bind(key))
		_buttons[key] = btn
		row.add_child(btn)
	vbox.add_child(row)

	_status = Label.new()
	_status.text = ""
	_status.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_status.add_theme_font_size_override("font_size", 11)
	_status.add_theme_color_override("font_color", Color(0.55, 0.75, 0.55))
	vbox.add_child(_status)

	_set_armed(false)


func on_ai_move(description: String, turn: int, move_seq: int) -> void:
	# A new AI move arrived. If the previous one was never rated it is simply
	# dropped (treated as "ignored"). Light up for the new move.
	_pending_desc = description
	_pending_turn = turn
	_pending_seq = move_seq
	_move_label.text = description
	_status.text = ""
	_set_armed(true)


func _set_armed(armed: bool) -> void:
	_armed = armed
	for key in _buttons:
		var btn: Button = _buttons[key]
		btn.disabled = not armed
		var col: Color = BUTTONS[key][1]
		btn.add_theme_color_override("font_color", col if armed else col.darkened(0.5))
	if armed:
		_glow = 1.0
		set_process(true)
	else:
		_glow = 0.0
		_border.border_color = Color(0.30, 0.32, 0.42)
		set_process(false)


func _process(delta: float) -> void:
	# Pulse the border while a move awaits rating.
	if not _armed:
		return
	_glow = fmod(_glow + delta * 1.5, 2.0)
	var t: float = abs(1.0 - _glow)   # 0..1 triangle wave
	_border.border_color = Color(0.30, 0.32, 0.42).lerp(Color(0.85, 0.72, 0.35), t)


func _on_sentiment(sentiment: String) -> void:
	if not _armed:
		return
	var game_id := ""
	if _game_id_provider.is_valid():
		game_id = str(_game_id_provider.call())
	if game_id.is_empty():
		game_id = "game"
	var body := {
		"game_id": game_id,
		"sentiment": sentiment,
		"turn": _pending_turn,
		"move_seq": _pending_seq,
		"move_desc": _pending_desc,
	}
	var url := _agent_base_url() + "/move_feedback"
	var err := _http.request(url, ["Content-Type: application/json"],
		HTTPClient.METHOD_POST, JSON.stringify(body))
	if err != OK:
		_status.add_theme_color_override("font_color", Color(0.85, 0.45, 0.45))
		_status.text = "send failed"
		return
	_status.add_theme_color_override("font_color", Color(0.55, 0.75, 0.55))
	_status.text = "recorded: %s" % sentiment
	_set_armed(false)


func _on_request_completed(_result: int, response_code: int, _headers: PackedStringArray, _body: PackedByteArray) -> void:
	if response_code != 200:
		_status.add_theme_color_override("font_color", Color(0.85, 0.45, 0.45))
		_status.text = "save error %d" % response_code
