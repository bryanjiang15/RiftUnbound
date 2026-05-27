class_name CommandConsole
extends VBoxContainer

signal command_submitted(player_index: int, text: String)

const MAX_LOG_LINES: int = 500

# Tracks which player the console is currently accepting input for.
# Updated externally via update_prompt().
var _active_player: int = 0

# ── Feature flag ─────────────────────────────────────────────────────────────
## When true, a hint bar appears below the input field showing the syntax for
## whatever verb has been typed so far. Toggle with the 'hints on' / 'hints off'
## commands, or set this before _ready().
var show_hints: bool = true

# ── Nodes ─────────────────────────────────────────────────────────────────────
var _log_lines: Array[String] = []
var _output_log: RichTextLabel
var _input_bar: HBoxContainer
var _prompt_label: Label
var _input_field: LineEdit
var _hint_bar: PanelContainer
var _hint_label: Label

# ── Color theme ───────────────────────────────────────────────────────────────
const COLOR_EVENT    = Color(0.8,  0.85, 0.8)
const COLOR_P1       = Color(0.9,  0.5,  0.5)
const COLOR_P2       = Color(0.5,  0.7,  0.9)
const COLOR_BG       = Color(0.04, 0.04, 0.07)
const COLOR_INPUT_BG = Color(0.06, 0.06, 0.10)
const COLOR_HINT_BG  = Color(0.07, 0.07, 0.12)
const COLOR_HINT_FG  = Color(0.55, 0.65, 0.55)
const COLOR_HINT_KW  = Color(0.75, 0.85, 0.65)
const COLOR_HINT_DIM = Color(0.40, 0.45, 0.40)

# ── Hint database ─────────────────────────────────────────────────────────────
# Each entry: verb → { usage, params, example, note? }
const HINTS: Dictionary = {
	"tap": {
		"usage": "tap rune-<n>",
		"params": "rune-<n>  Index of the channeled rune to exhaust (rune-0, rune-1 …)",
		"example": "tap rune-0",
		"note": "Adds 1 Energy to your Rune Pool."
	},
	"recycle": {
		"usage": "recycle rune-<n>",
		"params": "rune-<n>  Index of the channeled rune to recycle",
		"example": "recycle rune-1",
		"note": "Removes the rune and adds 1 domain Power to your pool."
	},
	"play": {
		"usage": "play <id> [to <location>] [target <id>] [from champion|hidden] [accelerate]",
		"params": (
			"<id>          Instance ID of the card to play\n" +
			"to <location> Where to place a unit: base | battlefield-a | battlefield-b\n" +
			"target <id>   Target permanent for spells/abilities\n" +
			"from champion Play the Chosen Champion from the Champion Zone\n" +
			"from hidden   Play a face-down Hidden card at a Battlefield\n" +
			"accelerate    Pay +1 ENG +1 Power to enter Ready instead of Exhausted"
		),
		"example": "play noxus-hopeful to battlefield-a"
	},
	"move": {
		"usage": "move <id> [id …] to <location>",
		"params": (
			"<id>          One or more unit instance IDs to move simultaneously\n" +
			"to <location> Destination: base | battlefield-a | battlefield-b\n" +
			"              Ganking keyword required for Battlefield→Battlefield moves"
		),
		"example": "move noxus-hopeful noxus-soldier to battlefield-a",
		"note": "Costs Exhaust per unit. Triggers Contested if opponent is present."
	},
	"use": {
		"usage": "use <card-id> [target <id>]",
		"params": (
			"<card-id>  Instance ID of the permanent with the activated ability\n" +
			"target <id>  Target for the ability (if required)"
		),
		"example": "use iron-shield-gear target noxus-hopeful"
	},
	"react": {
		"usage": "react <card-id> [target <id>]",
		"params": (
			"<card-id>   Reaction card in hand to place on the Chain\n" +
			"target <id>  Optional target"
		),
		"example": "react counter-protocol target void-seeker",
		"note": "Only valid during Closed states (Neutral Closed / Showdown Closed)."
	},
	"pass": {
		"usage": "pass",
		"params": "No arguments.",
		"example": "pass",
		"note": "Pass Priority (Chain), Focus (Showdown), or end Main Phase."
	},
	"end": {
		"usage": "end turn",
		"params": "Must type 'turn' after 'end'.",
		"example": "end turn",
		"note": "Ends your Main Phase and passes the turn."
	},
	"mulligan": {
		"usage": "mulligan <id> [id]  |  mulligan keep",
		"params": (
			"<id> [id]  Up to 2 card instance IDs from your hand to set aside\n" +
			"keep       Keep your current hand (skip mulligan)"
		),
		"example": "mulligan noxus-hopeful  |  mulligan keep"
	},
	"choose": {
		"usage": "choose <id>  |  choose none",
		"params": (
			"<id>   The instance ID or choice value the engine prompted for\n" +
			"none   Decline an optional choice"
		),
		"example": "choose noxus-hopeful"
	},
	"assign": {
		"usage": "assign <amount> to <id>  |  assign done",
		"params": (
			"<amount>  Damage points to assign\n" +
			"<id>      Target unit instance ID\n" +
			"done      Confirm all assignments are complete"
		),
		"example": "assign 3 to iron-juggernaut"
	},
	"hand": {
		"usage": "hand",
		"params": "No arguments.",
		"example": "hand",
		"note": "Prints your current hand to the log."
	},
	"board": {
		"usage": "board",
		"params": "No arguments.",
		"example": "board",
		"note": "Prints the full board state."
	},
	"card": {
		"usage": "card <card-id>",
		"params": "<card-id>  Definition ID (e.g. noxus-hopeful) — not instance ID",
		"example": "card noxus-hopeful"
	},
	"chain": {
		"usage": "chain",
		"params": "No arguments.",
		"example": "chain",
		"note": "Prints all items currently on the Chain."
	},
	"score": {
		"usage": "score",
		"params": "No arguments.",
		"example": "score"
	},
	"pool": {
		"usage": "pool",
		"params": "No arguments.",
		"example": "pool",
		"note": "Prints your current Rune Pool (Energy + Power available)."
	},
	"zones": {
		"usage": "zones",
		"params": "No arguments.",
		"example": "zones",
		"note": "Prints card counts for all zones of both players."
	},
	"help": {
		"usage": "help",
		"params": "No arguments.",
		"example": "help"
	},
	"hints": {
		"usage": "hints on  |  hints off",
		"params": "'on' or 'off' to toggle the typing-hint bar.",
		"example": "hints off"
	},
	"new": {
		"usage": "new game",
		"params": "Must type 'game' after 'new'.",
		"example": "new game",
		"note": "Restarts the game with the same decks."
	},
	"menu": {
		"usage": "menu",
		"params": "No arguments.",
		"example": "menu",
		"note": "Return to the main menu to choose a different match type."
	},
}


func _ready() -> void:
	_build_ui()


func _build_ui() -> void:
	var sb = StyleBoxFlat.new()
	sb.bg_color = COLOR_BG
	sb.border_color = Color(0.2, 0.2, 0.3)
	sb.set_border_width_all(1)
	add_theme_stylebox_override("panel", sb)

	# Output log
	_output_log = RichTextLabel.new()
	_output_log.bbcode_enabled = true
	_output_log.scroll_following = true
	_output_log.selection_enabled = true
	_output_log.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_output_log.custom_minimum_size = Vector2(0, 200)
	_output_log.add_theme_color_override("default_color", COLOR_EVENT)
	_output_log.add_theme_color_override("background_color", COLOR_BG)
	_output_log.add_theme_font_size_override("normal_font_size", 12)
	add_child(_output_log)

	add_child(HSeparator.new())

	# Hint bar (shown above input when show_hints is true)
	_hint_bar = PanelContainer.new()
	_hint_bar.name = "HintBar"
	var hint_sb = StyleBoxFlat.new()
	hint_sb.bg_color = COLOR_HINT_BG
	hint_sb.border_color = Color(0.2, 0.3, 0.2)
	hint_sb.set_border_width_all(1)
	hint_sb.content_margin_left = 8
	hint_sb.content_margin_right = 8
	hint_sb.content_margin_top = 3
	hint_sb.content_margin_bottom = 3
	_hint_bar.add_theme_stylebox_override("panel", hint_sb)
	_hint_label = Label.new()
	_hint_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_hint_label.add_theme_font_size_override("font_size", 11)
	_hint_label.add_theme_color_override("font_color", COLOR_HINT_FG)
	_hint_bar.add_child(_hint_label)
	add_child(_hint_bar)
	_hint_bar.visible = false  # hidden until user types

	# Input bar
	_input_bar = HBoxContainer.new()
	_input_bar.custom_minimum_size = Vector2(0, 30)
	add_child(_input_bar)

	_prompt_label = Label.new()
	_prompt_label.text = "[P1] > "
	_prompt_label.add_theme_color_override("font_color", COLOR_P1)
	_prompt_label.add_theme_font_size_override("font_size", 13)
	_prompt_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	_input_bar.add_child(_prompt_label)

	_input_field = LineEdit.new()
	_input_field.placeholder_text = "p1 <command>  or  p2 <command>   (hints on/off)"
	_input_field.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_input_field.add_theme_color_override("font_color", Color(0.9, 0.95, 0.9))
	_input_field.add_theme_color_override("font_placeholder_color", Color(0.38, 0.38, 0.42))
	var input_sb = StyleBoxFlat.new()
	input_sb.bg_color = COLOR_INPUT_BG
	input_sb.border_color = Color(0.3, 0.3, 0.4)
	input_sb.set_border_width_all(1)
	input_sb.content_margin_left = 6
	_input_field.add_theme_stylebox_override("normal", input_sb)
	_input_bar.add_child(_input_field)

	_input_field.text_submitted.connect(_on_input_submitted)
	_input_field.text_changed.connect(_on_text_changed)
	_input_field.grab_focus()

	add_welcome_message()


func add_welcome_message() -> void:
	add_line("> [color=#b0e0b0]Riftbound TCG — Console Interface[/color]")
	add_line("> [color=#888]Commands start with the acting player: 'p1 mulligan keep', 'p2 tap rune-0'[/color]")
	add_line("> [color=#888]Type 'help' for a full command list. Hints: type 'hints off' to disable.[/color]")
	add_line("")


# ── Log output ────────────────────────────────────────────────────────────────

func add_line(text: String) -> void:
	_log_lines.append(text)
	if _log_lines.size() > MAX_LOG_LINES:
		_log_lines = _log_lines.slice(_log_lines.size() - MAX_LOG_LINES)
	_output_log.append_text(_format_line(text) + "\n")


func _format_line(text: String) -> String:
	if text.begins_with("[PROMPT]"):
		return "[color=#d4c84a]" + _escape(text) + "[/color]"
	elif text.begins_with("[ERROR]"):
		return "[color=#d44444]" + _escape(text) + "[/color]"
	elif text.begins_with("[INFO]"):
		return "[color=#7ab0cc]" + _escape(text) + "[/color]"
	elif text.begins_with("> [P1]"):
		return "[color=#d48080]" + _escape(text) + "[/color]"
	elif text.begins_with("> [P2]"):
		return "[color=#80a8d4]" + _escape(text) + "[/color]"
	elif text.begins_with("> GAME OVER"):
		return "[b][color=#ffee44]" + _escape(text) + "[/color][/b]"
	elif text.begins_with(">"):
		return "[color=#a0c8a0]" + _escape(text) + "[/color]"
	elif text.begins_with("===") or text.begins_with("---"):
		return "[color=#606080]" + _escape(text) + "[/color]"
	return "[color=#c8c8cc]" + _escape(text) + "[/color]"


func _escape(text: String) -> String:
	return text.replace("[", "[lb]")


# ── Prompt label ──────────────────────────────────────────────────────────────

func update_prompt(player_index: int, _in_showdown: bool) -> void:
	_active_player = player_index
	_prompt_label.text = "[P%d] > " % (player_index + 1)
	_prompt_label.add_theme_color_override("font_color",
		COLOR_P1 if player_index == 0 else COLOR_P2)


# ── Hint system ───────────────────────────────────────────────────────────────

func set_hints_enabled(enabled: bool) -> void:
	show_hints = enabled
	if not enabled:
		_hint_bar.visible = false


func _on_text_changed(new_text: String) -> void:
	if not show_hints:
		_hint_bar.visible = false
		return

	var trimmed := new_text.strip_edges()
	if trimmed.is_empty():
		_hint_bar.visible = false
		return

	var tokens := trimmed.to_lower().split(" ", false)

	# Skip the player prefix when looking up verb hints
	var offset := 0
	if tokens.size() > 0 and (tokens[0] == "p1" or tokens[0] == "p2"):
		offset = 1
	if tokens.size() <= offset:
		_hint_bar.visible = false
		return

	var verb := tokens[offset]
	var hint := _get_hint(verb, tokens.slice(offset))

	if hint.is_empty():
		_hint_bar.visible = false
	else:
		_hint_label.text = hint
		_hint_bar.visible = true


func _get_hint(verb: String, tokens: Array) -> String:
	# Exact match
	if HINTS.has(verb):
		return _format_hint(verb, tokens)

	# Prefix match — find all verbs that start with what has been typed
	var matches: Array[String] = []
	for v in HINTS.keys():
		if v.begins_with(verb):
			matches.append(v)

	if matches.size() == 1:
		return _format_hint(matches[0], tokens)
	elif matches.size() > 1:
		matches.sort()
		return "Commands: " + "  |  ".join(matches)

	return ""


func _format_hint(verb: String, tokens: Array) -> String:
	var h: Dictionary = HINTS[verb]
	var usage: String = h.get("usage", "")
	var params: String = h.get("params", "")
	var example: String = h.get("example", "")
	var note: String = h.get("note", "")

	# Build a compact single-line hint when early in typing,
	# expand to multi-line details once the verb is complete.
	var verb_done = tokens.size() > 1 or (tokens.size() == 1 and tokens[0] == verb)

	if not verb_done:
		# Still typing the verb — just show usage
		return "  %s" % usage

	# Full hint: usage + params (condensed) + optional note
	var lines: Array[String] = []
	lines.append("  %s" % usage)
	if not params.is_empty():
		# Indent each param line
		for p in params.split("\n"):
			lines.append("    %s" % p)
	if not example.is_empty():
		lines.append("  e.g. %s" % example)
	if not note.is_empty():
		lines.append("  ↳ %s" % note)
	return "\n".join(lines)


# ── Input submission ──────────────────────────────────────────────────────────

func _on_input_submitted(text: String) -> void:
	_input_field.clear()
	_hint_bar.visible = false
	_input_field.grab_focus()

	var trimmed := text.strip_edges()
	if trimmed.is_empty():
		return

	# Handle 'hints on/off' locally without going to GameController
	var lower := trimmed.to_lower()
	if lower == "hints on":
		set_hints_enabled(true)
		add_line("> Typing hints enabled.")
		return
	elif lower == "hints off":
		set_hints_enabled(false)
		add_line("> Typing hints disabled.")
		return

	# Parse optional player prefix: "p1 <command>" or "p2 <command>".
	# Falls back to _active_player when no prefix is given.
	var player_index := _active_player
	var command := trimmed
	var first_space := trimmed.find(" ")
	if first_space > 0:
		var first_word := trimmed.left(first_space).to_lower()
		if first_word == "p1":
			player_index = 0
			command = trimmed.substr(first_space).strip_edges()
		elif first_word == "p2":
			player_index = 1
			command = trimmed.substr(first_space).strip_edges()
	else:
		# Single bare word like "p1" or "p2" — ignore
		if lower == "p1" or lower == "p2":
			return

	# Echo to log with resolved player tag
	add_line("> [P%d] %s" % [player_index + 1, command])
	command_submitted.emit(player_index, command)
