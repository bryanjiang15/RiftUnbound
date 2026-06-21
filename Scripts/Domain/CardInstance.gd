class_name CardInstance

var definition: CardDefinition
var instance_id: String = ""
var owner_index: int = -1

# Location tracking
var location: String = ""
var battlefield_index: int = -1

# Permanent state
var is_exhausted: bool = false
var is_stunned: bool = false
var damage: int = 0
var buff_counters: int = 0

# Combat designations
var is_attacker: bool = false
var is_defender: bool = false

# Gear attachment
var attached_gear: Array = []
var attached_to: CardInstance = null

# Temporary (this-turn) effects
var temp_might_bonus: int = 0
var temp_keywords: Array = []
var passive_keywords: Array = []
# Recomputed by TriggerDispatcher.emit_passive_auras from conditional passive
# Might abilities (e.g. "while alone", "while you have 8+ runes") and Legend auras.
var passive_might_bonus: int = 0

# Tracking
var played_this_turn: bool = false
var is_face_down: bool = false


func _init(def: CardDefinition, inst_id: String, owner_idx: int) -> void:
	definition = def
	instance_id = inst_id
	owner_index = owner_idx


func get_base_might() -> int:
	return definition.might + buff_counters + temp_might_bonus \
		+ passive_might_bonus + _gear_might_bonus()


func get_current_might() -> int:
	var base = get_base_might()
	if is_attacker:
		base += get_keyword_value("assault")
	if is_defender:
		base += get_keyword_value("shield")
	return base


# Net might gained (+) or lost (-) relative to the card's printed might.
func get_might_delta() -> int:
	return get_current_might() - definition.might


func _gear_might_bonus() -> int:
	var total := 0
	for gear in attached_gear:
		if gear.definition.might_bonus != null and gear.definition.might_bonus != "":
			total += int(str(gear.definition.might_bonus).replace("+", ""))
	return total


# Breakdown of every might contribution beyond the printed base might.
# Each entry is { "source": String, "symbol": String, "amount": int } where the
# amount is signed. Used by the UI to label where might was gained or lost from.
func get_might_breakdown() -> Array:
	var parts: Array = []
	if buff_counters != 0:
		parts.append({ "source": "buff", "symbol": "★", "amount": buff_counters })
	if temp_might_bonus != 0:
		parts.append({ "source": "temp", "symbol": "⚡", "amount": temp_might_bonus })
	if passive_might_bonus != 0:
		parts.append({ "source": "passive", "symbol": "✦", "amount": passive_might_bonus })
	var gear_bonus := _gear_might_bonus()
	if gear_bonus != 0:
		parts.append({ "source": "gear", "symbol": "⚙", "amount": gear_bonus })
	if is_attacker:
		var assault := get_keyword_value("assault")
		if assault != 0:
			parts.append({ "source": "assault", "symbol": "⚔", "amount": assault })
	if is_defender:
		var shield := get_keyword_value("shield")
		if shield != 0:
			parts.append({ "source": "shield", "symbol": "🛡", "amount": shield })
	return parts


func has_keyword(keyword_id: String) -> bool:
	for kw in definition.keywords:
		if kw.get("id", "") == keyword_id:
			return true
	for kw in passive_keywords:
		if kw.get("id", "") == keyword_id:
			return true
	for kw in temp_keywords:
		if kw.get("id", "") == keyword_id:
			return true
	if attached_to == null:
		for gear in attached_gear:
			for kw in gear.definition.attached_keywords:
				if kw.get("id", "") == keyword_id:
					return true
	return false


# Keyword values stack: a unit holding the same keyword from multiple sources
# (e.g. printed Shield 2 plus a combat-granted Shield 1) sums their values.
func get_keyword_value(keyword_id: String) -> int:
	var total := 0
	for kw in definition.keywords:
		if kw.get("id", "") == keyword_id:
			total += kw.get("value", 1)
	for kw in passive_keywords:
		if kw.get("id", "") == keyword_id:
			total += kw.get("value", 1)
	for kw in temp_keywords:
		if kw.get("id", "") == keyword_id:
			total += kw.get("value", 1)
	for gear in attached_gear:
		for kw in gear.definition.attached_keywords:
			if kw.get("id", "") == keyword_id:
				total += kw.get("value", 1)
	return total


func has_lethal_damage() -> bool:
	var might = get_current_might()
	return damage >= might and might > 0


func is_at_battlefield() -> bool:
	return battlefield_index >= 0 and location.begins_with("battlefield")


func is_at_base() -> bool:
	return location == "base"


func clear_temp_effects() -> void:
	temp_might_bonus = 0
	temp_keywords.clear()
	passive_keywords.clear()
	played_this_turn = false


# Remove keywords that were granted only for the duration of a single combat
# (e.g. Fortified Position's Shield 2 "this combat").
func clear_combat_effects() -> void:
	var kept: Array = []
	for kw in temp_keywords:
		if kw is Dictionary and kw.get("duration", "") == "combat":
			continue
		kept.append(kw)
	temp_keywords = kept


func apply_stun() -> void:
	is_stunned = true


func clear_stun() -> void:
	is_stunned = false


func ready() -> void:
	is_exhausted = false


func exhaust() -> void:
	is_exhausted = true


func add_damage(amount: int) -> void:
	damage += amount


func heal_all() -> void:
	damage = 0


func add_buff() -> void:
	buff_counters = mini(buff_counters + 1, 1)


func spend_buff() -> bool:
	if buff_counters <= 0:
		return false
	buff_counters -= 1
	return true


func display_name() -> String:
	if is_face_down:
		return "[hidden]"
	return definition.name


func status_string() -> String:
	var tags: Array[String] = []
	if is_exhausted:
		tags.append("EXH")
	if is_stunned:
		tags.append("STUN")
	if damage > 0:
		tags.append("DMG:%d" % damage)
	if buff_counters > 0:
		tags.append("BUFF+%d" % buff_counters)
	if is_attacker:
		tags.append("ATK")
	if is_defender:
		tags.append("DEF")
	return " ".join(tags) if not tags.is_empty() else "ready"


func short_description() -> String:
	var s = "[%s] %s" % [instance_id, definition.name]
	if definition.card_type == "unit":
		s += " (%d/%d MHT)" % [get_current_might(), definition.might]
	s += " — " + status_string()
	return s
