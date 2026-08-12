extends SceneTree

const TcgAssertions = preload("res://Scripts/Tests/Tcg/TcgAssertions.gd")
const RuleSetupTests = preload("res://Scripts/Tests/Tcg/suites/RuleSetupTests.gd")
const RuleTurnStructureTests = preload("res://Scripts/Tests/Tcg/suites/RuleTurnStructureTests.gd")
const RuleScoringTests = preload("res://Scripts/Tests/Tcg/suites/RuleScoringTests.gd")
const RuleScoreFeaturesTests = preload("res://Scripts/Tests/Tcg/suites/RuleScoreFeaturesTests.gd")
const RuleMovementTests = preload("res://Scripts/Tests/Tcg/suites/RuleMovementTests.gd")
const RuleCombatTests = preload("res://Scripts/Tests/Tcg/suites/RuleCombatTests.gd")
const RuleShowdownTests = preload("res://Scripts/Tests/Tcg/suites/RuleShowdownTests.gd")
const RuleChainTests = preload("res://Scripts/Tests/Tcg/suites/RuleChainTests.gd")
const RuleCleanupTests = preload("res://Scripts/Tests/Tcg/suites/RuleCleanupTests.gd")
const RuleResourcesTests = preload("res://Scripts/Tests/Tcg/suites/RuleResourcesTests.gd")
const CardScenarioTests = preload("res://Scripts/Tests/Tcg/suites/CardScenarioTests.gd")
const MasterYiDeckTests = preload("res://Scripts/Tests/Tcg/suites/MasterYiDeckTests.gd")
const RuleSimulationTests = preload("res://Scripts/Tests/Tcg/suites/RuleSimulationTests.gd")
const RuleSearchTests = preload("res://Scripts/Tests/Tcg/suites/RuleSearchTests.gd")
const RuleReasonerTests = preload("res://Scripts/Tests/Tcg/suites/RuleReasonerTests.gd")
const RuleEvaluationTests = preload("res://Scripts/Tests/Tcg/suites/RuleEvaluationTests.gd")
const RuleAnalysisStateTests = preload("res://Scripts/Tests/Tcg/suites/RuleAnalysisStateTests.gd")

const SUITE_ORDER: Array[String] = [
	"RuleSetup",
	"RuleTurnStructure",
	"RuleScoring",
	"RuleScoreFeatures",
	"RuleMovement",
	"RuleCombat",
	"RuleShowdown",
	"RuleChain",
	"RuleCleanup",
	"RuleResources",
	"CardScenario",
	"MasterYiDeck",
	"RuleSimulation",
	"RuleSearch",
	"RuleReasoner",
	"RuleEvaluation",
	"RuleAnalysisState",
]

const SUITES := {
	"RuleSetup": RuleSetupTests,
	"RuleTurnStructure": RuleTurnStructureTests,
	"RuleScoring": RuleScoringTests,
	"RuleScoreFeatures": RuleScoreFeaturesTests,
	"RuleMovement": RuleMovementTests,
	"RuleCombat": RuleCombatTests,
	"RuleShowdown": RuleShowdownTests,
	"RuleChain": RuleChainTests,
	"RuleCleanup": RuleCleanupTests,
	"RuleResources": RuleResourcesTests,
	"CardScenario": CardScenarioTests,
	"MasterYiDeck": MasterYiDeckTests,
	"RuleSimulation": RuleSimulationTests,
	"RuleSearch": RuleSearchTests,
	"RuleReasoner": RuleReasonerTests,
	"RuleEvaluation": RuleEvaluationTests,
	"RuleAnalysisState": RuleAnalysisStateTests,
}


func _initialize() -> void:
	var user_args := OS.get_cmdline_user_args()

	if user_args.has("--list"):
		for name in SUITE_ORDER:
			print(name)
		quit(0)
		return

	var selected := _parse_suite_args(user_args)
	if selected.is_empty() and not user_args.is_empty():
		quit(1)
		return

	var assertions = TcgAssertions.new()
	var run_all := selected.is_empty()
	for name in SUITE_ORDER:
		if run_all or name in selected:
			SUITES[name].run(assertions)

	var total = assertions.pass_count + assertions.fail_count
	print("TEST SUMMARY: %d/%d passed" % [assertions.pass_count, total])
	if assertions.fail_count > 0:
		for f in assertions.failures:
			print(f)
		quit(1)
	else:
		quit(0)


func _parse_suite_args(user_args: PackedStringArray) -> Array[String]:
	var selected: Array[String] = []
	for arg in user_args:
		if arg == "--":
			continue
		if arg.begins_with("-"):
			print("Unknown option: %s" % arg)
			_print_usage()
			return []
		if not SUITES.has(arg):
			print("Unknown suite: %s" % arg)
			_print_usage()
			return []
		if arg not in selected:
			selected.append(arg)
	return selected


func _print_usage() -> void:
	print("Usage: run_tcg_tests.sh [suite ...]")
	print("       run_tcg_tests.sh --list")
	print("Suites: %s" % ", ".join(SUITE_ORDER))
