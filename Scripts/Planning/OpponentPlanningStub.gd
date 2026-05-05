extends Resource
class_name OpponentPlanningStub

## Local-test opponent layout (Phase C). Not the Phase E ghost pipeline.

@export var placements: Array[OpponentPlacementEntry] = []

func apply_to(board: BoardState, scope: InstanceIdScope) -> void:
	if board == null or scope == null:
		return
	board.clear_opponent_champions()
	for p in placements:
		if p == null or p.champion == null:
			continue
		var gc := GridCoord.from_square(p.square)
		board.place_opponent_champion(p.champion, gc, scope)
