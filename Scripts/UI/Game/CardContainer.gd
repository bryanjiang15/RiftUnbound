extends Container
class_name CardContainer

## Base container for CardUI widgets.
##
## Manages card instantiation, removal, fan/arc layout, and selection hooks.
## Ported from the card-game-framework's hand/container pattern (Godot 3 → 4).
## HandUI and HandStrip extend this class to specialise selection behaviour.

@export_category("Details")
@export var zone: GameState.Zone
@export var flip := false

@export_category("Config")
@export var max_card_rotation: float = 20
@export var maximum_separation: int = 128
@export var vertical_scale: int = 8
@export var tween_time: float = 0.1
@export var rows: int = 1 # TODO: Implement multi-row layout

@export_category("Requisites")
@export var card_ui: PackedScene
@export var default_spawn: Node2D

## Populate from a live GameState. Syncs existing CardUI children with the
## zone contents, then lays them out in the fan.
func populate(state: GameState, index: int) -> void:
	print("Fetching cards in player ", index, "'s ", zone)
	var existing_cards: Array[CardData] = []
	for child: CardUI in get_children():
		if not state.get_player_zone(index, zone).has(child.referenced_card):
			child.queue_free()
		else:
			existing_cards.append(child.referenced_card)
	for card in state.get_player_zone(index, zone):
		if existing_cards.has(card):
			continue
		var ui: CardUI = card_ui.instantiate()
		ui.initialize(card, state)
		add_child(ui)
		if default_spawn != null:
			ui.global_position = default_spawn.global_position
		if flip:
			ui.rotation = PI
	await get_tree().process_frame
	await set_locations()
	for ui: CardUI in get_children():
		if not ui is CardUI:
			continue
		ui.selected.connect(func(card: CardData):
			_select_card_hook(card, state, index))
		ui.alt_selected.connect(func(card: CardData):
			_alt_select_card_hook(card, state, index))

## Fan / arc layout ported from the card-game-framework (Godot 4 syntax).
##
## Cards are distributed symmetrically around the horizontal centre of the
## container and arced upward toward the edges. Each card is gently rotated
## outward to reinforce the fan shape. Only CardUI children are considered.
func set_locations() -> void:
	var cards: Array = get_children().filter(func(c: Node) -> bool: return c is CardUI)
	if cards.is_empty():
		return
	var n: int = cards.size()
	var max_sep: float = min(float(maximum_separation), size.x / float(n + 1))
	var center_x: float = size.x / 2.0
	var center_y: float = size.y * 0.4
	var last_tween: Tween
	for i in n:
		if cards[i].is_queued_for_deletion():
			continue
		var card_offset: float = float(i) - float(n - 1) / 2.0
		var target_pos := Vector2(
			center_x + card_offset * max_sep,
			center_y + abs(card_offset + 0.5) * float(vertical_scale)
		)
		var target_rot: float = (card_offset + 0.5) / float(n) * max_card_rotation
		var tw: Tween = get_tree().create_tween().set_parallel()
		tw.tween_property(cards[i], "position", target_pos, tween_time)
		tw.tween_property(cards[i], "rotation_degrees", target_rot, tween_time)
		last_tween = tw
	if last_tween:
		await last_tween.finished

## Populates the hand from a plain list of cards without a GameState.
##
## Useful for the planning phase where no active game state is needed.
## Connects each card's `selected` signal to `_select_card_hook(card, null, -1)`.
func populate_from_card_list(cards: Array[CardData]) -> void:
	for child in get_children():
		child.queue_free()
	if card_ui == null:
		push_warning("CardContainer.populate_from_card_list: card_ui PackedScene not set")
		return
	for card in cards:
		var ui: CardUI = card_ui.instantiate()
		ui.referenced_card = card
		add_child(ui)
	await get_tree().process_frame
	await set_locations()
	for ui: CardUI in get_children():
		if not ui is CardUI:
			continue
		if ui.selected.is_connected(_on_planning_card_selected):
			continue
		ui.selected.connect(_on_planning_card_selected)

func _on_planning_card_selected(card: CardData) -> void:
	_select_card_hook(card, null, -1)

## Override in subclasses to handle primary card selection.
func _select_card_hook(_card: CardData, _state: GameState, _index: int) -> void:
	pass

## Override in subclasses to handle secondary (alt) card selection.
func _alt_select_card_hook(_card: CardData, _state: GameState, _index: int) -> void:
	pass
