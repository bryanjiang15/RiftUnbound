extends Resource
class_name PlanningSnapshot

## Immutable-ish planning lock passed to combat (Phase D). Duplicate before resolving if mutating.

@export var schema_version: int = 1
@export var round_index: int = 0
@export var run_id: String = ""

## RefCounted rows are not saved on disk as subresources; in-memory / programmatic only for Phase A.
var player_champions: Array[ChampionInstance] = []
var opponent_champions: Array[ChampionInstance] = []

## Deployed allies / card-units on grid (TODO when ally combat is in scope).
var deployed_allies: Array[CardInstance] = []

## Keys from GridCoord.to_key(); values: `{ "kind": "champion"|"ally", "instance_id": int }`.
var occupancy: Dictionary = {}
