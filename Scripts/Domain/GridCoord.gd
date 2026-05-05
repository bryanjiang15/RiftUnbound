extends Resource
class_name GridCoord

## Board cell for planning and combat. Base slice uses SQUARE_GRID and `square`.
## Champions and deployed allies share the same coordinate space in PlanningSnapshot.

enum CoordSystem { SQUARE_GRID, AXIAL_HEX }

@export var coord_system: CoordSystem = CoordSystem.SQUARE_GRID
@export var square: Vector2i = Vector2i.ZERO
@export var axial_q: int = 0
@export var axial_r: int = 0

static func from_square(p: Vector2i) -> GridCoord:
	var g := GridCoord.new()
	g.coord_system = CoordSystem.SQUARE_GRID
	g.square = p
	return g

static func from_axial(q: int, r: int) -> GridCoord:
	var g := GridCoord.new()
	g.coord_system = CoordSystem.AXIAL_HEX
	g.axial_q = q
	g.axial_r = r
	return g

func to_key() -> String:
	match coord_system:
		CoordSystem.SQUARE_GRID:
			return "sq:%d,%d" % [square.x, square.y]
		CoordSystem.AXIAL_HEX:
			return "hex:%d,%d" % [axial_q, axial_r]
	return "invalid"
