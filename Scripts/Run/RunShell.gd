extends Control

## Top-level coordinator for the run_shell scene.
##
## Wires RunController, PlanningController, RunHud, PlanningBoardView,
## ChampionRosterStrip, and ItemPoolStrip together at _ready time.
## Also handles visibility toggling of the planning section and
## forwarding debug button presses to RunController.

@onready var run_controller: RunController = $RunController
@onready var planning_controller: PlanningController = $PlanningController
@onready var run_hud: RunHud = $ScrollContainer/VBoxContainer/MarginTop/RunHud
@onready var planning_section: VBoxContainer = $ScrollContainer/VBoxContainer/PlanningSection
@onready var board_view: PlanningBoardView = $ScrollContainer/VBoxContainer/PlanningSection/PlanningBoardView
@onready var roster_strip: ChampionRosterStrip = $ScrollContainer/VBoxContainer/PlanningSection/ChampionRosterStrip
@onready var item_strip: HandStrip = $ScrollContainer/VBoxContainer/PlanningSection/HandStrip

func _ready() -> void:
	run_hud.bind_controller(run_controller)
	run_controller.planning_advance_rejected.connect(_on_planning_advance_rejected)
	run_controller.phase_changed.connect(_on_phase_changed)

	board_view.bind_controller(planning_controller)
	roster_strip.bind(planning_controller, board_view)
	item_strip.bind(planning_controller, board_view)
	planning_controller.board_reset.connect(_on_board_reset)

	_update_planning_section_visibility(run_controller.get_current_phase())

func _on_phase_changed(phase: RoundPhase.Phase) -> void:
	_update_planning_section_visibility(phase)

func _update_planning_section_visibility(phase: RoundPhase.Phase) -> void:
	planning_section.visible = (phase == RoundPhase.Phase.PLANNING)

func _on_planning_advance_rejected(errors: PackedStringArray) -> void:
	push_warning("Planning advance rejected: %s" % ", ".join(errors))
	run_hud.show_planning_error(errors)

## Requests the planning phase to lock and advance to combat resolution.
func _on_end_planning_pressed() -> void:
	run_controller.request_advance_from_planning()

## Triggers the stub combat resolver while in COMBAT_RESOLVE.
func _on_resolve_combat_pressed() -> void:
	run_controller.request_resolve_combat_stub()

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
