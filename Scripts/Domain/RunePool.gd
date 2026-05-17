class_name RunePool

var energy: int = 0
var power: Dictionary = {}


func add_energy(amount: int) -> void:
	energy += amount


func add_power(domain_name: String, amount: int) -> void:
	power[domain_name] = power.get(domain_name, 0) + amount


func can_pay(energy_cost: int, power_cost: Array) -> bool:
	if energy < energy_cost:
		return false
	for pc in power_cost:
		var needed: int = pc.get("amount", 0)
		var d: String = pc.get("domain", "")
		if d == "any":
			var total = 0
			for v in power.values():
				total += v
			if total < needed:
				return false
		else:
			if power.get(d, 0) < needed:
				return false
	return true


func pay(energy_cost: int, power_cost: Array) -> void:
	energy -= energy_cost
	for pc in power_cost:
		var d: String = pc.get("domain", "")
		var needed: int = pc.get("amount", 0)
		if d == "any":
			var remaining = needed
			for dk in power.keys():
				if remaining <= 0:
					break
				var take = mini(power[dk], remaining)
				power[dk] -= take
				remaining -= take
		else:
			power[d] = power.get(d, 0) - needed


func empty() -> void:
	energy = 0
	power.clear()


func total_energy() -> int:
	return energy


func total_power() -> int:
	var total = 0
	for v in power.values():
		total += v
	return total


func describe() -> String:
	var parts: Array[String] = []
	parts.append("ENG:%d" % energy)
	for d in power:
		if power[d] > 0:
			parts.append("%s:%d" % [CardDefinition._domain_abbr(d), power[d]])
	return " | ".join(parts) if not parts.is_empty() else "empty"
