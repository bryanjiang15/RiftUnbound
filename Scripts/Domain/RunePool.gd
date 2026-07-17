class_name RunePool

const SPELL_RAINBOW_POWER := "spell_rainbow"

var energy: int = 0
var power: Dictionary = {}


func add_energy(amount: int) -> void:
	energy += amount


func add_power(domain_name: String, amount: int) -> void:
	power[domain_name] = power.get(domain_name, 0) + amount


func can_pay(energy_cost: int, power_cost: Array, context: Dictionary = {}) -> bool:
	if energy < energy_cost:
		return false
	var sim_power := power.duplicate()
	return _consume_power(sim_power, power_cost, context, false)


func pay(energy_cost: int, power_cost: Array, context: Dictionary = {}) -> void:
	energy -= energy_cost
	_consume_power(power, power_cost, context, true)


func _consume_power(pool: Dictionary, power_cost: Array, context: Dictionary, mutate: bool) -> bool:
	var can_use_spell_rainbow := str(context.get("card_type", "")) == "spell"
	for pc in power_cost:
		var needed: int = pc.get("amount", 0)
		var d: String = pc.get("domain", "")
		if d == "any":
			var total = 0
			for v in pool.values():
				total += v
			if total < needed:
				return false
			if mutate:
				var remaining = needed
				for dk in pool.keys():
					if remaining <= 0:
						break
					var take = mini(pool[dk], remaining)
					pool[dk] -= take
					remaining -= take
		else:
			var matching_power: int = pool.get(d, 0)
			var rainbow_power: int = pool.get(SPELL_RAINBOW_POWER, 0) if can_use_spell_rainbow else 0
			if matching_power + rainbow_power < needed:
				return false
			if mutate:
				var from_matching = mini(matching_power, needed)
				pool[d] = pool.get(d, 0) - from_matching
				var remaining_specific = needed - from_matching
				if remaining_specific > 0:
					pool[SPELL_RAINBOW_POWER] = pool.get(SPELL_RAINBOW_POWER, 0) - remaining_specific
	return true


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
			var label := "RNB(spell)" if d == SPELL_RAINBOW_POWER else CardDefinition._domain_abbr(d)
			parts.append("%s:%d" % [label, power[d]])
	return " | ".join(parts) if not parts.is_empty() else "empty"


# Deep-copy this rune pool (Phase 2.5 simulation). No CardInstance references.
func clone() -> RunePool:
	var r := RunePool.new()
	r.energy = energy
	r.power = power.duplicate()
	return r
