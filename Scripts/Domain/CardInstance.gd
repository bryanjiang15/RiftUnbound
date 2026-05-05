extends RefCounted
class_name CardInstance

## Runtime card (item, equipment, ally, spell). Prefer this over mutating CardData runtime fields.

var definition: CardData
var instance_id: int = 0
var owner: int = 0
var controller: int = 0

static func from_definition(def: CardData, id_scope: InstanceIdScope, p_owner: int = 0, p_controller: int = 0) -> CardInstance:
	var inst := CardInstance.new()
	inst.definition = def
	inst.instance_id = id_scope.next()
	inst.owner = p_owner
	inst.controller = p_controller
	return inst
