extends Area2D
class_name CardUI

## Card widget: Area2D root with a Control child for visuals.
##
## Ported from the card-game-framework's Card pattern (Godot 3 → 4):
## - Input is handled via $Control.gui_input so it works correctly inside
##   both Control-based UI layouts and 2D scenes.
## - Hover scale tween runs on $Control so it's independent of node position.
## - selected / alt_selected signals are unchanged so HandStrip._select_card_hook
##   keeps working without modification.

signal selected(card: CardData)
signal alt_selected(card: CardData)

@export var referenced_card: CardData

@onready var _control: Control = $Control

func _ready() -> void:
	refresh()
	_control.mouse_entered.connect(_on_mouse_entered)
	_control.mouse_exited.connect(_on_mouse_exited)
	_control.gui_input.connect(_on_gui_input)

## Populates visual labels and artwork from referenced_card.
func refresh() -> void:
	if referenced_card == null:
		return
	var bg: TextureRect = _control.get_node_or_null("BG")
	var title: Label = _control.get_node_or_null("VBox/HBox/Title")
	var cost: Label = _control.get_node_or_null("VBox/HBox/Cost")
	var card_image: TextureRect = _control.get_node_or_null("VBox/CardImage")
	var type_label: Label = _control.get_node_or_null("VBox/TypeLabel")
	var desc: Label = _control.get_node_or_null("VBox/Description")

	if title != null:
		title.text = referenced_card.title if referenced_card.title != "" else "(card)"
	if cost != null:
		cost.text = str(referenced_card.cost)
	if card_image != null:
		card_image.texture = referenced_card.image
		card_image.visible = referenced_card.image != null
	if type_label != null:
		type_label.text = _type_string(referenced_card.card_kind)
	if desc != null:
		desc.text = referenced_card.text

## Called by CardContainer.populate / populate_from_card_list when initialising from a game state.
func initialize(card: CardData, _state: GameState) -> void:
	referenced_card = card

func _on_mouse_entered() -> void:
	get_tree().create_tween().tween_property(_control, "scale", Vector2.ONE * 1.15, 0.1)

func _on_mouse_exited() -> void:
	get_tree().create_tween().tween_property(_control, "scale", Vector2.ONE, 0.1)

func _on_gui_input(event: InputEvent) -> void:
	if event.is_action_released("Select"):
		selected.emit(referenced_card)
	if event.is_action_released("Alt Select"):
		alt_selected.emit(referenced_card)

static func _type_string(kind: CardData.CardType) -> String:
	match kind:
		CardData.CardType.EQUIPMENT: return "Equipment"
		CardData.CardType.ITEM:      return "Item"
		CardData.CardType.ALLY:      return "Ally"
		CardData.CardType.SPELL:     return "Spell"
		_:                           return ""
