extends RefCounted
class_name ChampionInstance

## Runtime champion on the board / in a planning lock. Not a CardData.

var definition: ChampionData
var instance_id: int = 0
## Display / rules hook until §4.5 leveling is modeled in combat.
var level: int = 1
var stats: CombatStats
var cell: GridCoord
var equipped: Array[CardInstance] = []

static func from_definition(
	def: ChampionData,
	id_scope: InstanceIdScope,
	p_cell: GridCoord
) -> ChampionInstance:
	var inst := ChampionInstance.new()
	inst.definition = def
	inst.instance_id = id_scope.next()
	inst.cell = p_cell
	if def.base_stats:
		inst.stats = def.base_stats.duplicate_for_instance()
		inst.stats.current_health = inst.stats.max_health
	else:
		inst.stats = CombatStats.new()
	return inst
