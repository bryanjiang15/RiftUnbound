extends Resource
class_name OpponentPlanningStub

## Hardcoded opponent layout used during local development (Phase C stub).
##
## Not connected to the Phase E ghost/replay pipeline. Configure placements in the
## inspector via DefaultOpponentStub.tres; swap the resource to test different boards.

@export var placements: Array[OpponentPlacementEntry] = []

## Clears the opponent side of `board` and re-places every entry from `placements`.
## Safe to call each round reset; entries with a null champion are silently skipped.
func apply_to(board: BoardState, scope: InstanceIdScope) -> void:
	if board == null or scope == null:
		return
	board.clear_opponent_champions()
	for p in placements:
		if p == null or p.champion == null:
			continue
		var gc := GridCoord.from_square(p.square)
		board.place_opponent_champion(p.champion, gc, scope)
