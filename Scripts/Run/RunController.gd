extends Node
class_name RunController

## Central state machine driving a single run from start to end.
##
## Owns RunState and InstanceIdScope for the active run, transitions between
## PLANNING → COMBAT_RESOLVE → ROUND_RESULT, applies damage/healing, and emits
## signals that RunHud and PlanningController listen to for UI / board updates.
## Debug buttons in RunShell call the `request_*` methods directly.

signal phase_changed(new_phase: RoundPhase.Phase)
signal run_health_changed(new_health: int)
signal run_ended(player_won_or_survived: bool)
signal round_advanced(new_round_index: int)
signal run_started
## Emitted when `request_advance_from_planning` fails validation (Phase C+).
signal planning_advance_rejected(errors: PackedStringArray)

## Optional preset from the inspector; if unset, `RunParams.new()` defaults apply.
@export var initial_run_params: RunParams
@export var planning_controller: PlanningController

var run_state: RunState
var scope: InstanceIdScope

var _phase: RoundPhase.Phase = RoundPhase.Phase.PLANNING
var _pending_outcome: CombatOutcome
var _last_snapshot: PlanningSnapshot

## Returns the phase the run is currently in.
func get_current_phase() -> RoundPhase.Phase:
	return _phase

## Returns the PlanningSnapshot locked when planning last ended, or null if the
## planning phase has not been completed yet this run.
func get_last_planning_snapshot() -> PlanningSnapshot:
	return _last_snapshot

func _ready() -> void:
	var params := initial_run_params
	if params == null:
		params = RunParams.new()
	start_run(params)

## Restarts using `initial_run_params` from the inspector, or `RunParams.new()` defaults.
func restart_run() -> void:
	var p: RunParams = initial_run_params
	if p == null:
		p = RunParams.new()
	start_run(p)

## Initialises a fresh RunState and InstanceIdScope, resets the phase to PLANNING,
## and emits phase_changed, run_health_changed, and run_started in order.
func start_run(params: RunParams) -> void:
	scope = InstanceIdScope.new()
	scope.reset(1)

	var rs := RunState.new(params)
	rs.run_id = _make_run_id()
	rs.current_round_index = 1
	rs.player_run_health = params.starting_player_health
	rs.is_terminal = false
	run_state = rs

	_phase = RoundPhase.Phase.PLANNING
	_pending_outcome = null
	_last_snapshot = null

	phase_changed.emit(_phase)
	run_health_changed.emit(run_state.player_run_health)
	run_started.emit()

## Attempts to lock the planning phase and move to COMBAT_RESOLVE.
## If PlanningController is set, validates the board first; emits planning_advance_rejected
## with error strings and returns early on any violation.
func request_advance_from_planning() -> void:
	if run_state == null or run_state.is_terminal:
		return
	if _phase != RoundPhase.Phase.PLANNING:
		push_warning("RunController: advance_from_planning ignored (phase=%s)" % RoundPhase.phase_to_string(_phase))
		return

	if planning_controller != null and planning_controller.board_state != null:
		var errs: PackedStringArray = planning_controller.validate_planning()
		if errs.size() > 0:
			planning_advance_rejected.emit(errs)
			return
		_last_snapshot = PlanningSnapshotBuilder.build(planning_controller.board_state, run_state)
	else:
		_last_snapshot = _build_planning_snapshot_stub()
	_phase = RoundPhase.Phase.COMBAT_RESOLVE
	phase_changed.emit(_phase)

## Runs the stub combat resolver and transitions to ROUND_RESULT.
## Must be called while in COMBAT_RESOLVE; ignored (with a warning) otherwise.
func request_resolve_combat_stub() -> void:
	if run_state == null or run_state.is_terminal:
		return
	if _phase != RoundPhase.Phase.COMBAT_RESOLVE:
		push_warning("RunController: resolve_combat_stub ignored (phase=%s)" % RoundPhase.phase_to_string(_phase))
		return

	_pending_outcome = stub_resolve_combat()
	_phase = RoundPhase.Phase.ROUND_RESULT
	phase_changed.emit(_phase)

## Applies the pending CombatOutcome: adjusts player health, checks terminal conditions,
## then either emits run_ended or advances to the next round and resets to PLANNING.
func request_apply_round_result() -> void:
	if run_state == null or run_state.is_terminal:
		return
	if _phase != RoundPhase.Phase.ROUND_RESULT:
		push_warning("RunController: apply_round_result ignored (phase=%s)" % RoundPhase.phase_to_string(_phase))
		return
	if _pending_outcome == null:
		push_error("RunController: no pending combat outcome")
		return

	var outcome := _pending_outcome
	_pending_outcome = null

	if outcome.player_won_round:
		var heal: int = run_state.params.healing_on_round_win
		if heal > 0:
			run_state.player_run_health = mini(
				run_state.player_run_health + heal,
				run_state.params.starting_player_health,
			)
			run_health_changed.emit(run_state.player_run_health)
	else:
		var dmg: int = RunRoundDamage.damage_on_loss(run_state.params, outcome)
		run_state.player_run_health -= dmg
		run_health_changed.emit(run_state.player_run_health)

	if run_state.player_run_health <= 0:
		run_state.is_terminal = true
		run_ended.emit(false)
		phase_changed.emit(_phase)
		return

	var max_r: int = run_state.params.max_rounds
	if max_r > 0 and run_state.current_round_index >= max_r:
		run_state.is_terminal = true
		run_ended.emit(true)
		phase_changed.emit(_phase)
		return

	run_state.current_round_index += 1
	round_advanced.emit(run_state.current_round_index)
	_phase = RoundPhase.Phase.PLANNING
	phase_changed.emit(_phase)

## Stub until Phase D: driven by `RunParams` flags or random coin flip.
func stub_resolve_combat() -> CombatOutcome:
	var o := CombatOutcome.new()
	var p: RunParams = run_state.params
	if p.stub_always_win:
		o.player_won_round = true
		o.enemy_survivor_count = 0
	elif p.stub_always_lose:
		o.player_won_round = false
		o.enemy_survivor_count = p.stub_enemy_survivors_on_loss
	else:
		o.player_won_round = randf() >= 0.5
		o.enemy_survivor_count = 0 if o.player_won_round else p.stub_enemy_survivors_on_loss
	return o

func _make_run_id() -> String:
	return "%d_%s" % [Time.get_unix_time_from_system(), str(randi())]

func _build_planning_snapshot_stub() -> PlanningSnapshot:
	var snap := PlanningSnapshot.new()
	snap.round_index = run_state.current_round_index
	snap.run_id = run_state.run_id
	snap.player_champions = []
	snap.opponent_champions = []
	snap.deployed_allies = []
	snap.occupancy = {}
	return snap
