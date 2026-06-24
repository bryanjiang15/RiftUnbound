class_name BoardState

class BattlefieldEntry:
	var card_def: CardDefinition
	var battlefield_id: String
	var display_name: String
	var controller_index: int = -1
	var units: Array = [[], []]  # Array[Array[CardInstance]], indexed by player_index
	var is_contested: bool = false
	var facedown_card: CardInstance = null
	var scored_by: Array = []  # player indices who scored this turn


var battlefields: Array = []

# Showdown/Combat tracking
var active_showdown_bf: int = -1
var active_combat_bf: int = -1
var staged_showdowns: Array = []
var staged_combats: Array = []


func setup(p1_battlefield_id: String, p2_battlefield_id: String) -> void:
	battlefields.clear()
	staged_showdowns.clear()
	staged_combats.clear()
	CardLoader.load_all()
	_add_battlefield(p1_battlefield_id, 0)
	_add_battlefield(p2_battlefield_id, 1)


func _add_battlefield(bf_id: String, index: int) -> void:
	var def = CardLoader.get_card(bf_id)
	if def == null:
		push_error("BoardState: unknown battlefield id '%s'" % bf_id)
		return
	var entry = BattlefieldEntry.new()
	entry.card_def = def
	entry.battlefield_id = "battlefield-%s" % _index_to_letter(index)
	entry.display_name = def.name
	entry.controller_index = -1
	entry.units = [[], []]
	battlefields.append(entry)


static func _index_to_letter(idx: int) -> String:
	return ["a", "b", "c", "d"][idx] if idx < 4 else str(idx)


func get_battlefield_by_id(bf_id: String) -> BattlefieldEntry:
	for bf in battlefields:
		if bf.battlefield_id == bf_id:
			return bf
	return null


func get_battlefield_index(bf_id: String) -> int:
	for i in range(battlefields.size()):
		if battlefields[i].battlefield_id == bf_id:
			return i
	return -1


func get_all_units_at(bf_index: int) -> Array:
	if bf_index < 0 or bf_index >= battlefields.size():
		return []
	var result: Array = []
	for player_units in battlefields[bf_index].units:
		result.append_array(player_units)
	return result


func get_units_at(bf_index: int, player_index: int) -> Array:
	if bf_index < 0 or bf_index >= battlefields.size():
		return []
	return battlefields[bf_index].units[player_index]


func get_all_units_on_board(player_index: int) -> Array:
	var result: Array = []
	for bf in battlefields:
		result.append_array(bf.units[player_index])
	return result


func add_unit_to_battlefield(unit: CardInstance, bf_index: int) -> void:
	if bf_index < 0 or bf_index >= battlefields.size():
		return
	var bf = battlefields[bf_index]
	bf.units[unit.owner_index].append(unit)
	unit.battlefield_index = bf_index
	unit.location = bf.battlefield_id


func remove_unit_from_battlefield(unit: CardInstance) -> void:
	var bf_idx = unit.battlefield_index
	if bf_idx < 0 or bf_idx >= battlefields.size():
		return
	battlefields[bf_idx].units[unit.owner_index].erase(unit)
	unit.battlefield_index = -1


func all_battlefield_ids() -> Array:
	var ids: Array = []
	for bf in battlefields:
		ids.append(bf.battlefield_id)
	return ids


func find_unit_on_board(inst_id: String) -> CardInstance:
	for bf in battlefields:
		for player_units in bf.units:
			for unit in player_units:
				if unit.instance_id == inst_id:
					return unit
	return null


func is_staged(bf_index: int) -> bool:
	return bf_index in staged_showdowns or bf_index in staged_combats


func battlefield_description(bf_index: int) -> String:
	if bf_index < 0 or bf_index >= battlefields.size():
		return ""
	var bf = battlefields[bf_index]
	var ctrl_str = "uncontrolled"
	if bf.controller_index >= 0:
		ctrl_str = "P%d" % (bf.controller_index + 1)
	if bf.is_contested:
		ctrl_str += " (CONTESTED)"
	var lines: Array[String] = []
	lines.append("  [%s] %s — %s" % [bf.battlefield_id, bf.display_name, ctrl_str])
	for pi in range(bf.units.size()):
		if not bf.units[pi].is_empty():
			var unit_strs: Array[String] = []
			for u in bf.units[pi]:
				unit_strs.append("%s(%d/%d)" % [
					u.instance_id, u.get_current_might(), u.definition.might
				])
			lines.append("    P%d: %s" % [pi + 1, ", ".join(unit_strs)])
	if bf.facedown_card:
		lines.append("    [hidden card]")
	return "\n".join(lines)


# Deep-copy the board through the shared identity map (Phase 2.5 simulation).
# Units and the face-down card resolve through `map` so they are the same
# objects the player zones and chain reference. card_def is shared (immutable).
func clone(map: Dictionary) -> BoardState:
	var b := BoardState.new()
	b.battlefields = []
	for bf in battlefields:
		var e := BattlefieldEntry.new()
		e.card_def = bf.card_def
		e.battlefield_id = bf.battlefield_id
		e.display_name = bf.display_name
		e.controller_index = bf.controller_index
		e.units = [[], []]
		for pi in range(bf.units.size()):
			var cloned_units: Array = []
			for u in bf.units[pi]:
				cloned_units.append(u.clone(map))
			e.units[pi] = cloned_units
		e.is_contested = bf.is_contested
		e.facedown_card = bf.facedown_card.clone(map) if bf.facedown_card != null else null
		e.scored_by = bf.scored_by.duplicate()
		b.battlefields.append(e)
	b.active_showdown_bf = active_showdown_bf
	b.active_combat_bf = active_combat_bf
	b.staged_showdowns = staged_showdowns.duplicate()
	b.staged_combats = staged_combats.duplicate()
	return b
