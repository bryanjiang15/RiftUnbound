class_name CardDefinition
extends Resource

@export var id: String = ""
@export var name: String = ""
@export var card_type: String = ""
@export var supertypes: Array = []
@export var tags: Array = []
@export var domain: Array = []
@export var energy_cost: int = 0
@export var power_cost: Array = []
@export var keywords: Array = []
@export var abilities: Array = []
@export var flavor_text: String = ""

# Unit fields
@export var might: int = 0
@export var might_bonus: Variant = null

# Gear fields
@export var attached_keywords: Array = []

# Spell fields
@export var is_action: bool = false
@export var is_reaction: bool = false

# Rune fields
@export var is_basic: bool = false

# Battlefield fields
@export var facedown_capacity: int = 1

# Legend fields
@export var champion_tag: String = ""

# Art — relative path under res://Assets/ (e.g. "CardArts/OGN-251.webp")
# Falls back to "Champ_Card.jpg" at display time if empty or unloadable.
@export var image: String = ""


func has_keyword(keyword_id: String) -> bool:
	for kw in keywords:
		if kw.get("id", "") == keyword_id:
			return true
	return false


func get_keyword_value(keyword_id: String) -> int:
	for kw in keywords:
		if kw.get("id", "") == keyword_id:
			return kw.get("value", 1)
	return 0


func is_champion() -> bool:
	return "champion" in supertypes


func is_token() -> bool:
	return "token" in supertypes


func cost_string() -> String:
	var parts: Array[String] = []
	if energy_cost > 0 or power_cost.is_empty():
		parts.append("[%d ENG]" % energy_cost)
	for pc in power_cost:
		var domain_abbr = _domain_abbr(pc.get("domain", ""))
		var amount = pc.get("amount", 1)
		parts.append("[%d %s]" % [amount, domain_abbr])
	return " ".join(parts) if not parts.is_empty() else "[0]"


static func _domain_abbr(domain_name: String) -> String:
	match domain_name:
		"fury": return "FRY"
		"calm": return "CLM"
		"mind": return "MND"
		"body": return "BDY"
		"chaos": return "CHS"
		"order": return "ORD"
		"any": return "ANY"
	return domain_name.to_upper().left(3)


static func domain_color(domain_name: String) -> Color:
	match domain_name:
		"fury": return Color(0.9, 0.2, 0.2)
		"calm": return Color(0.2, 0.8, 0.3)
		"mind": return Color(0.2, 0.4, 0.9)
		"body": return Color(0.9, 0.5, 0.1)
		"chaos": return Color(0.7, 0.1, 0.9)
		"order": return Color(0.9, 0.85, 0.1)
		"any": return Color(0.9, 0.9, 0.9)
	return Color(0.6, 0.6, 0.6)
