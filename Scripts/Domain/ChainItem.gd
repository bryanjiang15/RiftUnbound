class_name ChainItem

enum ItemType { CARD, ABILITY, DAMAGE_ASSIGNMENT }

var item_type: int = ItemType.CARD
var source_card: CardInstance = null
var ability_def: Dictionary = {}
var ability_index: int = -1
var targets: Array = []
var mode: String = ""
var owner_index: int = -1
var is_resolved: bool = false

# Pending target selection (set when resolution needs a choice)
var needs_target: bool = false
var target_prompt: String = ""
var target_filter: String = ""
var target_params: Dictionary = {}

# Damage assignment state (for combat)
var damage_assignments: Dictionary = {}
var remaining_might: int = 0
var valid_targets: Array = []


static func from_card(card: CardInstance) -> ChainItem:
	var item = ChainItem.new()
	item.item_type = ItemType.CARD
	item.source_card = card
	item.owner_index = card.owner_index
	return item


static func from_ability(card: CardInstance, ab: Dictionary, ab_idx: int) -> ChainItem:
	var item = ChainItem.new()
	item.item_type = ItemType.ABILITY
	item.source_card = card
	item.ability_def = ab
	item.ability_index = ab_idx
	item.owner_index = card.owner_index
	return item


func describe() -> String:
	var prefix = "P%d" % (owner_index + 1)
	if item_type == ItemType.CARD and source_card:
		return "[%s] %s" % [prefix, source_card.display_name()]
	elif item_type == ItemType.ABILITY and source_card:
		var ab_id = ability_def.get("ability_id", "?")
		return "[%s] Ability: %s (%s)" % [prefix, ab_id, source_card.display_name()]
	return "[%s] Chain item" % prefix


# Deep-copy this chain item through the shared identity map (Phase 2.5).
# CardInstance references (source_card, targets, valid_targets) resolve through
# `map`; dictionaries are deep-duplicated.
func clone(map: Dictionary) -> ChainItem:
	var item := ChainItem.new()
	item.item_type = item_type
	item.source_card = source_card.clone(map) if source_card != null else null
	item.ability_def = ability_def.duplicate(true)
	item.ability_index = ability_index
	item.targets = _clone_target_array(targets, map)
	item.mode = mode
	item.owner_index = owner_index
	item.is_resolved = is_resolved
	item.needs_target = needs_target
	item.target_prompt = target_prompt
	item.target_filter = target_filter
	item.target_params = target_params.duplicate(true)
	item.damage_assignments = damage_assignments.duplicate(true)
	item.remaining_might = remaining_might
	item.valid_targets = _clone_target_array(valid_targets, map)
	return item


static func _clone_target_array(arr: Array, map: Dictionary) -> Array:
	var out: Array = []
	for t in arr:
		if t is CardInstance:
			out.append(t.clone(map))
		elif t is Dictionary:
			out.append(t.duplicate(true))
		elif t is Array:
			out.append(_clone_target_array(t, map))
		else:
			out.append(t)
	return out
