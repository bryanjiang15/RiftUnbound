extends Resource
class_name GridSpec

## Square grid: each side is `columns` × `rows_per_side`. Opponent occupies rows [0, rows_per_side), player [rows_per_side, 2 * rows_per_side).
## Axial hex is reserved for a later milestone; iteration helpers only implement square for now.

@export var coord_system: GridCoord.CoordSystem = GridCoord.CoordSystem.SQUARE_GRID
@export var columns: int = 3
@export var rows_per_side: int = 5

func total_rows() -> int:
	return rows_per_side * 2

func is_in_bounds(coord: GridCoord) -> bool:
	if coord.coord_system != coord_system:
		return false
	match coord_system:
		GridCoord.CoordSystem.SQUARE_GRID:
			var x := coord.square.x
			var y := coord.square.y
			return x >= 0 and x < columns and y >= 0 and y < total_rows()
		GridCoord.CoordSystem.AXIAL_HEX:
			return false
	return false

func is_opponent_deployable(coord: GridCoord) -> bool:
	if not is_in_bounds(coord):
		return false
	return coord.square.y >= 0 and coord.square.y < rows_per_side

func is_player_deployable(coord: GridCoord) -> bool:
	if not is_in_bounds(coord):
		return false
	return coord.square.y >= rows_per_side and coord.square.y < total_rows()

## All square cells in row-major order (for UI iteration).
func iter_square_cells() -> Array[GridCoord]:
	var out: Array[GridCoord] = []
	if coord_system != GridCoord.CoordSystem.SQUARE_GRID:
		return out
	for y in range(total_rows()):
		for x in range(columns):
			out.append(GridCoord.from_square(Vector2i(x, y)))
	return out

static func default_square_5x3_two_sided() -> GridSpec:
	var g := GridSpec.new()
	g.coord_system = GridCoord.CoordSystem.SQUARE_GRID
	g.columns = 3
	g.rows_per_side = 5
	return g
