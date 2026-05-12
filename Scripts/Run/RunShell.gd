extends Control

## Top-level coordinator for the run_shell scene.
##
## Wires RunController, PlanningController, RunHud, PlanningBoardView,
## ChampionRosterStrip, HandStrip, and CombatBoardView together at _ready time.
## Handles phase-aware visibility: PlanningSection shown during PLANNING /
## ROUND_RESULT; CombatSection shown (with replay) during COMBAT_RESOLVE.

@onready var run_controller: RunController = $RunController
@onready var planning_controller: PlanningController = $PlanningController
@onready var run_hud: RunHud = $ScrollContainer/VBoxContainer/MarginTop/RunHud
@onready var planning_section: VBoxContainer = $ScrollContainer/VBoxContainer/PlanningSection
@onready var combat_section: VBoxContainer = $ScrollContainer/VBoxContainer/CombatSection
@onready var board_view: PlanningBoardView = $ScrollContainer/VBoxContainer/PlanningSection/PlanningBoardView
@onready var combat_board_view: CombatBoardView = $ScrollContainer/VBoxContainer/CombatSection/CombatBoardView
@onready var roster_strip: ChampionRosterStrip = $ScrollContainer/VBoxContainer/PlanningSection/ChampionRosterStrip
@onready var item_strip: HandStrip = $ScrollContainer/VBoxContainer/PlanningSection/HandStrip
@onready var apply_result_button: Button = $ScrollContainer/VBoxContainer/DebugSection/DebugPanel/ApplyRoundResultButton

func _ready() -> void:
	run_hud.bind_controller(run_controller)
	run_controller.planning_advance_rejected.connect(_on_planning_advance_rejected)
	run_controller.phase_changed.connect(_on_phase_changed)

	board_view.bind_controller(planning_controller)
	roster_strip.bind(planning_controller, board_view)
	item_strip.bind(planning_controller, board_view)
	planning_controller.board_reset.connect(_on_board_reset)

	combat_board_view.replay_finished.connect(_on_replay_finished)

	_update_section_visibility(run_controller.get_current_phase())

func _on_phase_changed(phase: RoundPhase.Phase) -> void:
	_update_section_visibility(phase)

func _update_section_visibility(phase: RoundPhase.Phase) -> void:
	match phase:
		RoundPhase.Phase.PLANNING:
			planning_section.visible = true
			combat_section.visible   = false
			apply_result_button.disabled = false
		RoundPhase.Phase.COMBAT_RESOLVE:
			# Auto-resolve combat (deferred to avoid re-entrancy in the signal handler).
			# This transitions immediately to ROUND_RESULT where the replay is shown.
			planning_section.visible = false
			combat_section.visible   = false
			call_deferred("_auto_resolve_combat")
		RoundPhase.Phase.ROUND_RESULT:
			planning_section.visible = false
			combat_section.visible   = true
			apply_result_button.disabled = true
			_start_replay_if_available()
		_:
			# Terminal state — leave whatever is visible as-is.
			pass

func _auto_resolve_combat() -> void:
	run_controller.request_resolve_combat()

func _start_replay_if_available() -> void:
	var outcome: CombatOutcome = run_controller.get_pending_outcome()
	if outcome == null or outcome.combat_result == null:
		apply_result_button.disabled = false
		return
	var snapshot: PlanningSnapshot = run_controller.get_last_planning_snapshot()
	var spec: GridSpec = planning_controller.grid_spec if planning_controller != null else GridSpec.default_square_5x3_two_sided()
	if snapshot == null:
		apply_result_button.disabled = false
		return
	combat_board_view.start_replay(outcome.combat_result, snapshot, spec)

func _on_replay_finished() -> void:
	apply_result_button.disabled = false

func _on_planning_advance_rejected(errors: PackedStringArray) -> void:
	push_warning("Planning advance rejected: %s" % ", ".join(errors))
	run_hud.show_planning_error(errors)

## Requests the planning phase to lock and advance to combat resolution.
func _on_end_planning_pressed() -> void:
	run_controller.request_advance_from_planning()

## Triggers combat resolution while in COMBAT_RESOLVE.
func _on_resolve_combat_pressed() -> void:
	run_controller.request_resolve_combat()

## Applies the pending round result (damage/healing) and advances to the next round.
func _on_apply_round_result_pressed() -> void:
	run_controller.request_apply_round_result()

func _on_board_reset() -> void:
	var board: BoardState = planning_controller.board_state
	if board != null:
		run_hud.update_opponent_label(board.opponent_champions.size())

## Resets the planning board to its initial state (opponent stub re-applied, player side cleared).
func _on_reset_layout_pressed() -> void:
	planning_controller.reset_board()

## Restarts the entire run from round 1 using the inspector's RunParams.
func _on_start_new_run_pressed() -> void:
	run_controller.restart_run()

## Returns to the main menu scene, discarding the current run.
func _on_back_to_menu_pressed() -> void:
	get_tree().change_scene_to_file("res://Scenes/UI/main_menu.tscn")
