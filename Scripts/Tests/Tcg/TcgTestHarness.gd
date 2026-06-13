class_name TcgTestHarness
extends RefCounted

const FixtureLoader = preload("res://Scripts/Tests/Tcg/FixtureLoader.gd")
const GameControllerScript = preload("res://Scripts/Game/GameController.gd")
const TriggerDispatcherScript = preload("res://Scripts/Game/TriggerDispatcher.gd")

var controller: GameController
const TcgAssertionsScript = preload("res://Scripts/Tests/Tcg/TcgAssertions.gd")
var assertions: TcgAssertions = TcgAssertionsScript.new()
var _pending_choices: Array[String] = []


func setup() -> void:
	controller = GameControllerScript.new()
	controller.skip_auto_start = true
	controller._ai_player_index = -1
	controller.trigger_dispatcher = TriggerDispatcherScript.new()
	controller.log_lines.clear()


func load_fixture(path: String) -> void:
	setup()
	FixtureLoader.load_into_controller(controller, path)


func load_fixture_dict(data: Dictionary) -> void:
	setup()
	FixtureLoader.load_from_dict(controller, data)


func set_choices(choices: Array) -> void:
	_pending_choices.clear()
	for choice in choices:
		_pending_choices.append(str(choice))


func cmd(player_index: int, command: String) -> void:
	_drain_prompts(player_index)
	controller.submit_command(player_index, command)
	_drain_prompts(player_index)
	_resolve_chain()
	_drain_prompts(player_index)


func _resolve_chain() -> void:
	var safety = 40
	while safety > 0:
		safety -= 1
		if not controller.gs.pending_prompt.is_empty():
			return
		if controller.gs.chain.is_empty():
			return
		if controller.gs.current_state != TurnStateMachine.State.NEUTRAL_CLOSED and \
				controller.gs.current_state != TurnStateMachine.State.SHOWDOWN_CLOSED:
			return
		var pi = controller.gs.priority_player_index
		controller.submit_command(pi, "pass")
		_drain_prompts(pi)


func cmd_with_choices(player_index: int, command: String, choices: Array) -> void:
	set_choices(choices)
	cmd(player_index, command)


func _drain_prompts(player_index: int) -> void:
	var safety = 20
	while safety > 0 and not controller.gs.pending_prompt.is_empty():
		safety -= 1
		var prompt_pi = controller.gs.pending_prompt.get("player_index", player_index)
		var choice = "none"
		if not _pending_choices.is_empty():
			choice = str(_pending_choices.pop_front())
		elif controller.gs.pending_prompt.get("type", "") == "choose_discard":
			var valid: Array = controller.gs.pending_prompt.get("valid_choices", [])
			choice = str(valid[0]) if not valid.is_empty() else "none"
		elif controller.gs.pending_prompt.get("type", "") == "choose_target":
			var valid: Array = controller.gs.pending_prompt.get("valid_choices", [])
			if not valid.is_empty():
				var v = valid[0]
				choice = v.instance_id if v is CardInstance else str(v)
			else:
				choice = "none"
		elif controller.gs.pending_prompt.get("type", "") == "choose_trash_return":
			var valid: Array = controller.gs.pending_prompt.get("valid_choices", [])
			choice = str(valid[0]) if not valid.is_empty() else "none"
		elif controller.gs.pending_prompt.get("type", "") == "choose_optional":
			choice = "yes"
		elif controller.gs.pending_prompt.get("type", "") == "choose_battlefield":
			var valid: Array = controller.gs.pending_prompt.get("valid_choices", [])
			choice = str(valid[0]) if not valid.is_empty() else "none"
		controller.submit_command(prompt_pi, "choose %s" % choice)
		if controller.last_command_error:
			break


func gs() -> GameState:
	return controller.gs


func assert_eq(actual: Variant, expected: Variant, test_name: String) -> void:
	assertions.assert_eq(actual, expected, test_name)


func assert_true(condition: bool, test_name: String, reason: String = "") -> void:
	assertions.assert_true(condition, test_name, reason)


func assert_no_error(test_name: String) -> void:
	assertions.assert_no_error(controller, test_name)


func assert_score(player_index: int, expected: int, test_name: String) -> void:
	assertions.assert_score(controller.gs, player_index, expected, test_name)


func assert_log_contains(substring: String, test_name: String) -> void:
	assertions.assert_log_contains(controller, substring, test_name)


func find_unit(instance_id: String) -> CardInstance:
	return controller.gs.find_instance_anywhere(instance_id)
