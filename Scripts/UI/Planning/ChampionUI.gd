extends Area2D
class_name ChampionUI

## Visual Area2D widget for a champion.
##
## Mirrors the CardUI Area2D pattern: Control child handles visuals and pointer
## events while the Area2D provides collision-based positioning in 2D space.
##
## Used in two contexts:
##   - ChampionRosterStrip: shows an unplaced champion the player can drag onto the board.
##   - PlanningBoardView: shows a placed champion token on a board cell.
##
## Drag-and-drop flow:
##   1. LMB press fires drag_started(self).
##   2. PlanningBoardView creates a ghost and tracks mouse until LMB release.
##   3. On release over a valid cell: place (roster) or move (board token).
##   4. On release outside valid cell (roster): selects the champion def for click-to-place.

signal drag_started(ui: ChampionUI)
signal right_clicked(ui: ChampionUI)

## The champion definition displayed by this widget.
@export var definition: ChampionData

## -1 when in the roster (not yet placed). Set by PlanningBoardView for board tokens.
var instance_id: int = -1

@onready var _control: Control = $Control

func _ready() -> void:
	refresh()
	_control.mouse_entered.connect(_on_mouse_entered)
	_control.mouse_exited.connect(_on_mouse_exited)
	_control.gui_input.connect(_on_gui_input)

## Updates portrait and name label from the current definition.
func refresh() -> void:
	if definition == null:
		return
	var portrait: TextureRect = _control.get_node_or_null("Portrait")
	var name_lbl: Label = _control.get_node_or_null("NameLabel")
	if portrait != null:
		portrait.texture = definition.portrait
		portrait.visible = definition.portrait != null
	if name_lbl != null:
		name_lbl.text = definition.display_name if definition.display_name != "" else "?"

func _on_mouse_entered() -> void:
	get_tree().create_tween().tween_property(_control, "scale", Vector2.ONE * 1.1, 0.1)

func _on_mouse_exited() -> void:
	get_tree().create_tween().tween_property(_control, "scale", Vector2.ONE, 0.1)

func _on_gui_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		if mb.button_index == MOUSE_BUTTON_LEFT and mb.pressed:
			drag_started.emit(self)
		elif mb.button_index == MOUSE_BUTTON_RIGHT and mb.pressed:
			right_clicked.emit(self)
