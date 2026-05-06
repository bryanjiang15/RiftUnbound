extends Resource
class_name GridSpec

## Describes the shape of the planning grid.
##
## The board is split into two equal halves stacked vertically:
##   - Opponent rows: y ∈ [0, rows_per_side)
##   - Player rows:   y ∈ [rows_per_side, 2 * rows_per_side)
## Axial hex layout is reserved for a later milestone; all current helpers assume SQUARE_GRID.

@export var coord_system: GridCoord.CoordSystem = GridCoord.CoordSystem.SQUARE_GRID
@export var columns: int = 5
@export var rows_per_side: int = 3

## Total number of rows across both sides (opponent + player).
func total_rows() -> int:
	return rows_per_side * 2

## Returns true if `coord` falls within the grid boundaries and matches `coord_system`.
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

## Returns true if `coord` is a valid cell for the opponent to occupy (top half).
func is_opponent_deployable(coord: GridCoord) -> bool:
	if not is_in_bounds(coord):
		return false
	return coord.square.y >= 0 and coord.square.y < rows_per_side

## Returns true if `coord` is a valid cell for the player to place champions (bottom half).
func is_player_deployable(coord: GridCoord) -> bool:
	if not is_in_bounds(coord):
		return false
	return coord.square.y >= rows_per_side and coord.square.y < total_rows()

## Returns every cell in the grid in row-major order (top-left → bottom-right).
## Used by PlanningBoardView to build the visual grid.
func iter_square_cells() -> Array[GridCoord]:
	var out: Array[GridCoord] = []
	if coord_system != GridCoord.CoordSystem.SQUARE_GRID:
		return out
	for y in range(total_rows()):
		for x in range(columns):
			out.append(GridCoord.from_square(Vector2i(x, y)))
	return out

## Convenience factory: 5-column × 3-row-per-side square grid (used as the runtime default).
static func default_square_5x3_two_sided() -> GridSpec:
	var g := GridSpec.new()
	g.coord_system = GridCoord.CoordSystem.SQUARE_GRID
	g.columns = 5
	g.rows_per_side = 3
	return g
