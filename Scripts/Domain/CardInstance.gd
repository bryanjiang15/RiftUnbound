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

# Tracking
var played_this_turn: bool = false
var is_face_down: bool = false


func _init(def: CardDefinition, inst_id: String, owner_idx: int) -> void:
	definition = def
	instance_id = inst_id
	owner_index = owner_idx


func get_base_might() -> int:
	var base = definition.might + buff_counters + temp_might_bonus
	for gear in attached_gear:
		if gear.definition.might_bonus != null and gear.definition.might_bonus != "":
			base += int(str(gear.definition.might_bonus).replace("+", ""))
	return base


func get_current_might() -> int:
	var base = get_base_might()
	if is_attacker:
		base += get_keyword_value("assault")
	if is_defender:
		base += get_keyword_value("shield")
	return base


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


func get_keyword_value(keyword_id: String) -> int:
	for kw in definition.keywords:
		if kw.get("id", "") == keyword_id:
			return kw.get("value", 1)
	for kw in passive_keywords:
		if kw.get("id", "") == keyword_id:
			return kw.get("value", 1)
	for kw in temp_keywords:
		if kw.get("id", "") == keyword_id:
			return kw.get("value", 1)
	for gear in attached_gear:
		for kw in gear.definition.attached_keywords:
			if kw.get("id", "") == keyword_id:
				return kw.get("value", 1)
	return 0


func has_lethal_damage() -> bool:
	return damage >= get_base_might() and get_base_might() > 0


func is_at_battlefield() -> bool:
	return battlefield_index >= 0 and location.begins_with("battlefield")


func is_at_base() -> bool:
	return location == "base"


func clear_temp_effects() -> void:
	temp_might_bonus = 0
	temp_keywords.clear()
	passive_keywords.clear()
	played_this_turn = false


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
