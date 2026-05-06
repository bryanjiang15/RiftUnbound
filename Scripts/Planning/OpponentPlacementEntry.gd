extends Resource
class_name OpponentPlacementEntry

## A single entry in an OpponentPlanningStub describing which champion goes where.
##
## `square` uses the same (column, row) convention as GridCoord.square for SQUARE_GRID:
## x = column index (0-based), y = row index within [0, rows_per_side).

@export var champion: ChampionData
@export var square: Vector2i = Vector2i.ZERO
