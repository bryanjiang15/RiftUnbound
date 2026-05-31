extends SceneTree

const TcgAssertions = preload("res://Scripts/Tests/Tcg/TcgAssertions.gd")
const RuleSetupTests = preload("res://Scripts/Tests/Tcg/suites/RuleSetupTests.gd")
const RuleTurnStructureTests = preload("res://Scripts/Tests/Tcg/suites/RuleTurnStructureTests.gd")
const RuleScoringTests = preload("res://Scripts/Tests/Tcg/suites/RuleScoringTests.gd")
const RuleMovementTests = preload("res://Scripts/Tests/Tcg/suites/RuleMovementTests.gd")
const RuleCombatTests = preload("res://Scripts/Tests/Tcg/suites/RuleCombatTests.gd")
const RuleShowdownTests = preload("res://Scripts/Tests/Tcg/suites/RuleShowdownTests.gd")
const RuleChainTests = preload("res://Scripts/Tests/Tcg/suites/RuleChainTests.gd")
const RuleCleanupTests = preload("res://Scripts/Tests/Tcg/suites/RuleCleanupTests.gd")
const RuleResourcesTests = preload("res://Scripts/Tests/Tcg/suites/RuleResourcesTests.gd")
const CardScenarioTests = preload("res://Scripts/Tests/Tcg/suites/CardScenarioTests.gd")

func _initialize() -> void:
	var assertions = TcgAssertions.new()
	RuleSetupTests.run(assertions)
	RuleTurnStructureTests.run(assertions)
	RuleScoringTests.run(assertions)
	RuleMovementTests.run(assertions)
	RuleCombatTests.run(assertions)
	RuleShowdownTests.run(assertions)
	RuleChainTests.run(assertions)
	RuleCleanupTests.run(assertions)
	RuleResourcesTests.run(assertions)
	CardScenarioTests.run(assertions)

	var total = assertions.pass_count + assertions.fail_count
	print("TEST SUMMARY: %d/%d passed" % [assertions.pass_count, total])
	if assertions.fail_count > 0:
		for f in assertions.failures:
			print(f)
		quit(1)
	else:
		quit(0)
