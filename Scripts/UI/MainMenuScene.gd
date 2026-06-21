extends Control

const DECKS_DIR := "res://Data/Decks/"
const DEFAULT_P1_DECK := "res://Data/Decks/starter-deck-p1.json"
const DEFAULT_P2_DECK := "res://Data/Decks/starter-deck-p2.json"

# Discovered decks: array of { "label": String, "path": String }
var _decks: Array = []
var _p1_picker: OptionButton
var _p2_picker: OptionButton


func _ready() -> void:
	_load_deck_list()
	_build_ui()


func _load_deck_list() -> void:
	_decks.clear()
	var dir := DirAccess.open(DECKS_DIR)
	if dir == null:
		push_warning("MainMenuScene: could not open %s" % DECKS_DIR)
		return
	var file_names := dir.get_files()
	file_names.sort()
	for file_name in file_names:
		if not file_name.ends_with(".json"):
			continue
		var path := DECKS_DIR + file_name
		_decks.append({
			"label": _deck_label_for(path, file_name),
			"path": path,
		})


func _deck_label_for(path: String, fallback: String) -> String:
	var text := FileAccess.get_file_as_string(path)
	if text != "":
		var parsed = JSON.parse_string(text)
		if typeof(parsed) == TYPE_DICTIONARY and parsed.has("player_label"):
			return str(parsed["player_label"])
	return fallback.get_basename()


func _build_ui() -> void:
	# Dark background
	var bg := ColorRect.new()
	bg.color = Color(0.04, 0.04, 0.07)
	bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(bg)

	# Center container
	var center := CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(center)

	var vbox := VBoxContainer.new()
	vbox.alignment = BoxContainer.ALIGNMENT_CENTER
	vbox.add_theme_constant_override("separation", 28)
	vbox.custom_minimum_size = Vector2(560, 0)
	center.add_child(vbox)

	# Title
	var title := Label.new()
	title.text = "RIFT UNBOUND"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 72)
	title.add_theme_color_override("font_color", Color(0.85, 0.72, 0.35))
	vbox.add_child(title)

	# Subtitle
	var subtitle := Label.new()
	subtitle.text = "Choose Your Match"
	subtitle.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	subtitle.add_theme_font_size_override("font_size", 22)
	subtitle.add_theme_color_override("font_color", Color(0.55, 0.60, 0.75))
	vbox.add_child(subtitle)

	# Spacer
	var spacer := Control.new()
	spacer.custom_minimum_size = Vector2(0, 20)
	vbox.add_child(spacer)

	# Deck selection — choose which deck each player pilots
	var deck_panel := _make_deck_selectors()
	vbox.add_child(deck_panel)

	# Player vs Player
	var pvp_entry := _make_entry(
		"Player vs Player",
		"Both players share the command console",
		Color(0.18, 0.42, 0.72),
		Color(0.24, 0.52, 0.88)
	)
	pvp_entry.get_node("Button").pressed.connect(_on_pvp_pressed)
	vbox.add_child(pvp_entry)

	# Player vs AI
	var pvai_entry := _make_entry(
		"Player vs AI",
		"P1 uses the console  —  P2 is controlled by AI",
		Color(0.52, 0.20, 0.20),
		Color(0.68, 0.26, 0.26)
	)
	pvai_entry.get_node("Button").pressed.connect(_on_pvai_pressed)
	vbox.add_child(pvai_entry)

	# Footer
	var footer := Label.new()
	footer.text = "v0.1 — Riftbound Simulation"
	footer.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	footer.add_theme_font_size_override("font_size", 14)
	footer.add_theme_color_override("font_color", Color(0.32, 0.32, 0.42))
	vbox.add_child(footer)


func _make_entry(label_text: String, desc_text: String, color_bg: Color, color_hover: Color) -> VBoxContainer:
	var wrapper := VBoxContainer.new()
	wrapper.add_theme_constant_override("separation", 6)

	var btn := Button.new()
	btn.name = "Button"
	btn.text = label_text
	btn.custom_minimum_size = Vector2(560, 72)
	btn.add_theme_font_size_override("font_size", 28)
	btn.add_theme_color_override("font_color", Color.WHITE)
	btn.add_theme_color_override("font_hover_color", Color.WHITE)
	btn.add_theme_color_override("font_pressed_color", Color.WHITE)

	var sn := StyleBoxFlat.new()
	sn.bg_color = color_bg
	sn.set_corner_radius_all(8)
	sn.set_border_width_all(2)
	sn.border_color = color_hover

	var sh := StyleBoxFlat.new()
	sh.bg_color = color_hover
	sh.set_corner_radius_all(8)
	sh.set_border_width_all(2)
	sh.border_color = Color(1.0, 1.0, 1.0, 0.35)

	btn.add_theme_stylebox_override("normal", sn)
	btn.add_theme_stylebox_override("hover", sh)
	btn.add_theme_stylebox_override("pressed", sn)
	btn.add_theme_stylebox_override("focus", sn)
	wrapper.add_child(btn)

	var desc := Label.new()
	desc.text = desc_text
	desc.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	desc.add_theme_font_size_override("font_size", 15)
	desc.add_theme_color_override("font_color", Color(0.58, 0.63, 0.76))
	wrapper.add_child(desc)

	return wrapper


func _make_deck_selectors() -> VBoxContainer:
	var wrapper := VBoxContainer.new()
	wrapper.add_theme_constant_override("separation", 10)

	var heading := Label.new()
	heading.text = "Deck Selection"
	heading.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	heading.add_theme_font_size_override("font_size", 18)
	heading.add_theme_color_override("font_color", Color(0.70, 0.74, 0.85))
	wrapper.add_child(heading)

	_p1_picker = _make_deck_picker("Player 1 Deck", DEFAULT_P1_DECK)
	wrapper.add_child(_p1_picker.get_parent())

	_p2_picker = _make_deck_picker("Player 2 Deck", DEFAULT_P2_DECK)
	wrapper.add_child(_p2_picker.get_parent())

	return wrapper


func _make_deck_picker(label_text: String, default_path: String) -> OptionButton:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	row.alignment = BoxContainer.ALIGNMENT_CENTER

	var label := Label.new()
	label.text = label_text
	label.custom_minimum_size = Vector2(160, 0)
	label.add_theme_font_size_override("font_size", 16)
	label.add_theme_color_override("font_color", Color(0.58, 0.63, 0.76))
	row.add_child(label)

	var picker := OptionButton.new()
	picker.custom_minimum_size = Vector2(360, 40)
	picker.add_theme_font_size_override("font_size", 16)
	for i in _decks.size():
		var deck: Dictionary = _decks[i]
		picker.add_item(str(deck["label"]), i)
		if str(deck["path"]) == default_path:
			picker.select(i)
	row.add_child(picker)

	return picker


func _selected_deck_path(picker: OptionButton, fallback: String) -> String:
	if picker == null:
		return fallback
	var idx := picker.get_selected_id()
	if idx < 0 or idx >= _decks.size():
		return fallback
	return str(_decks[idx]["path"])


func _apply_deck_overrides() -> void:
	Engine.set_meta("p1_deck", _selected_deck_path(_p1_picker, DEFAULT_P1_DECK))
	Engine.set_meta("p2_deck", _selected_deck_path(_p2_picker, DEFAULT_P2_DECK))


func _on_pvp_pressed() -> void:
	Engine.set_meta("game_mode", "pvp")
	_apply_deck_overrides()
	get_tree().change_scene_to_file("res://Scenes/GameScene.tscn")


func _on_pvai_pressed() -> void:
	Engine.set_meta("game_mode", "pvai")
	_apply_deck_overrides()
	get_tree().change_scene_to_file("res://Scenes/GameScene.tscn")
