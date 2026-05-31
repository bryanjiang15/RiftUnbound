class_name TcgAssertions

var pass_count: int = 0
var fail_count: int = 0
var failures: Array[String] = []


func reset() -> void:
	pass_count = 0
	fail_count = 0
	failures.clear()


func assert_true(condition: bool, test_name: String, reason: String = "") -> void:
	if condition:
		pass_count += 1
		print("TEST PASS: %s" % test_name)
	else:
		fail_count += 1
		var msg = "TEST FAIL: %s" % test_name
		if not reason.is_empty():
			msg += " — %s" % reason
		failures.append(msg)
		print(msg)


func assert_eq(actual: Variant, expected: Variant, test_name: String) -> void:
	assert_true(actual == expected, test_name, "expected %s, got %s" % [str(expected), str(actual)])


func assert_no_error(controller: GameController, test_name: String) -> void:
	assert_true(not controller.last_command_error, test_name, "command produced [ERROR]")


func assert_score(gs: GameState, player_index: int, expected: int, test_name: String) -> void:
	assert_eq(gs.players[player_index].score, expected, test_name)


func assert_phase(gs: GameState, expected: int, test_name: String) -> void:
	assert_eq(gs.current_phase, expected, test_name)


func assert_hand_size(gs: GameState, player_index: int, expected: int, test_name: String) -> void:
	assert_eq(gs.players[player_index].hand.size(), expected, test_name)


func assert_log_contains(controller: GameController, substring: String, test_name: String) -> void:
	var found = false
	for line in controller.log_lines:
		if substring in line:
			found = true
			break
	assert_true(found, test_name, "log missing '%s'" % substring)
