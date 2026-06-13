class_name PlayerState

var player_index: int = 0
var player_name: String = "P1"

# Zones
var deck: Array[CardInstance] = []
var rune_deck: Array[CardInstance] = []
var hand: Array[CardInstance] = []
var trash: Array[CardInstance] = []
var banishment: Array[CardInstance] = []
var base_permanents: Array[CardInstance] = []
var channeled_runes: Array[CardInstance] = []
var champion_zone: CardInstance = null
var legend: CardInstance = null

# Resources
var rune_pool: RunePool = RunePool.new()
var score: int = 0

# Turn tracking
var cards_played_this_turn: int = 0
var cards_discarded_count: int = 0
var discarded_this_turn: Array[CardInstance] = []
var battlefields_scored_this_turn: Array[int] = []

# Deck configuration (battlefield IDs from deck file)
var deck_battlefields: Array[String] = []

# Instance ID generation
var _id_counters: Dictionary = {}


func create_instance(card_def: CardDefinition) -> CardInstance:
	var base_id = card_def.id
	var count = _id_counters.get(base_id, 0) + 1
	_id_counters[base_id] = count
	var inst_id = base_id if count == 1 else "%s-%d" % [base_id, count]
	return CardInstance.new(card_def, inst_id, player_index)


func get_hand_instance(inst_id: String) -> CardInstance:
	for c in hand:
		if c.instance_id == inst_id:
			return c
	return null


func get_board_instance(inst_id: String) -> CardInstance:
	for c in base_permanents:
		if c.instance_id == inst_id:
			return c
	for c in channeled_runes:
		if c.instance_id == inst_id:
			return c
	if champion_zone and champion_zone.instance_id == inst_id:
		return champion_zone
	return null


func find_instance(inst_id: String) -> CardInstance:
	var c = get_hand_instance(inst_id)
	if c:
		return c
	c = get_board_instance(inst_id)
	if c:
		return c
	for tr in trash:
		if tr.instance_id == inst_id:
			return tr
	return null


func get_rune_by_index(rune_index: int) -> CardInstance:
	if rune_index < 0 or rune_index >= channeled_runes.size():
		return null
	return channeled_runes[rune_index]


func draw_card() -> CardInstance:
	if deck.is_empty():
		return null
	var card = deck.pop_front()
	card.location = "hand"
	hand.append(card)
	return card


func channel_rune() -> CardInstance:
	if rune_deck.is_empty():
		return null
	var rune = rune_deck.pop_front()
	rune.location = "rune_zone"
	rune.is_exhausted = false
	channeled_runes.append(rune)
	return rune


func shuffle_trash_into_deck() -> void:
	for c in trash:
		c.location = "deck"
	deck.append_array(trash)
	trash.clear()
	deck.shuffle()


func move_to_trash(inst: CardInstance) -> void:
	_remove_from_all_zones(inst)
	inst.location = "trash"
	inst.is_exhausted = false
	inst.damage = 0
	inst.buff_counters = 0
	inst.temp_might_bonus = 0
	inst.temp_keywords.clear()
	inst.is_attacker = false
	inst.is_defender = false
	inst.is_stunned = false
	trash.append(inst)


func move_to_banishment(inst: CardInstance) -> void:
	_remove_from_all_zones(inst)
	inst.location = "banishment"
	banishment.append(inst)


func move_to_hand(inst: CardInstance) -> void:
	_remove_from_all_zones(inst)
	inst.location = "hand"
	inst.clear_temp_effects()
	hand.append(inst)


func recycle_to_bottom(inst: CardInstance, is_rune: bool) -> void:
	_remove_from_all_zones(inst)
	if is_rune:
		inst.location = "rune_deck"
		rune_deck.append(inst)
	else:
		inst.location = "deck"
		deck.append(inst)


func remove_rune(rune: CardInstance) -> void:
	channeled_runes.erase(rune)


func _remove_from_all_zones(inst: CardInstance) -> void:
	hand.erase(inst)
	base_permanents.erase(inst)
	channeled_runes.erase(inst)
	trash.erase(inst)
	banishment.erase(inst)
	if champion_zone == inst:
		champion_zone = null


func get_units_at_base() -> Array[CardInstance]:
	var result: Array[CardInstance] = []
	for c in base_permanents:
		if c.definition.card_type == "unit":
			result.append(c)
	return result


func get_unattached_gear_at_base() -> Array[CardInstance]:
	var result: Array[CardInstance] = []
	for c in base_permanents:
		if c.definition.card_type == "gear" and c.attached_to == null:
			result.append(c)
	return result


func reset_turn_state() -> void:
	cards_played_this_turn = 0
	cards_discarded_count = 0
	discarded_this_turn.clear()
	battlefields_scored_this_turn.clear()
	for c in base_permanents:
		c.played_this_turn = false
	for c in hand:
		c.played_this_turn = false


func hand_description() -> String:
	if hand.is_empty():
		return "(empty hand)"
	var lines: Array[String] = []
	for c in hand:
		var cost_str = c.definition.cost_string()
		var type_str = c.definition.card_type.to_upper()
		if c.definition.card_type == "unit":
			lines.append("  %s | %s | %s | MHT:%d" % [
				c.instance_id, c.definition.name, cost_str, c.definition.might
			])
		else:
			lines.append("  %s | %s | %s | %s" % [
				c.instance_id, c.definition.name, cost_str, type_str
			])
	return "\n".join(lines)
