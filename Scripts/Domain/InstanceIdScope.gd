extends RefCounted
class_name InstanceIdScope

## Per-run monotonic ids for ChampionInstance / CardInstance (deterministic, log-friendly).

var _next: int = 1

func next() -> int:
	var id := _next
	_next += 1
	return id

func reset(start: int = 1) -> void:
	_next = start
