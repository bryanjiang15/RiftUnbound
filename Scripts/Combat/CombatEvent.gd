extends RefCounted
class_name CombatEvent

## A single timestamped entry in the combat log.
##
## Produced by CombatResolver for every action taken during combat.
## CombatBoardView consumes these to drive the visual replay.

enum Kind { MOVE, ATTACK, DEATH, COMBAT_START, COMBAT_END }

## Which tick this event occurred on (0-based).
var tick: int = 0
## The type of action.
var kind: Kind = Kind.MOVE
## instance_id of the acting unit.
var actor_id: int = 0
## Cell the actor occupies after the action (post-move for MOVE, unchanged for ATTACK).
var actor_cell: GridCoord
## instance_id of the target unit; -1 for MOVE / COMBAT_START / COMBAT_END.
var target_id: int = -1
## For MOVE: destination cell. For ATTACK: defender's cell. Null otherwise.
var target_cell: GridCoord
## Damage dealt (0 for non-ATTACK events).
var damage: int = 0
## Target's current_health after the hit; -1 for non-ATTACK events.
var target_health_after: int = -1
## True if the target died from this attack.
var died: bool = false
