extends Control


func _ready() -> void:
	_build_ui()


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


func _on_pvp_pressed() -> void:
	Engine.set_meta("game_mode", "pvp")
	get_tree().change_scene_to_file("res://Scenes/GameScene.tscn")


func _on_pvai_pressed() -> void:
	Engine.set_meta("game_mode", "pvai")
	get_tree().change_scene_to_file("res://Scenes/GameScene.tscn")
