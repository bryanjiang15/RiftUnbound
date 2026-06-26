class_name TurnSearch
extends RefCounted

const MoveSimulatorScript = preload("res://Scripts/Game/MoveSimulator.gd")
const ScoringProfileScript = preload("res://Scripts/Game/ScoringProfile.gd")

const DEFAULT_TOP_N := 5
const DEFAULT_BEAM_WIDTH := 8
const DEFAULT_NODE_BUDGET := 80
const DEFAULT_TIME_BUDGET_MS := 250
const DEFAULT_MAX_DEPTH := 6
# Reactive lines are short (navigate one response window), so they use a tighter
# depth bound than full-turn main search.
const DEFAULT_REACTIVE_MAX_DEPTH := 4

var _sim: MoveSimulator
var _scorer: ScoringProfile
var _ai_index: int = 1
# "main" = plan a whole turn from Neutral Open to end turn.
# "reactive" = navigate a chain/showdown response window until it resolves.
var _mode: String = "main"


func _init(profile_path: String = "") -> void:
	_sim = MoveSimulatorScript.new()
	# An explicit profile_path lets each AI seat search under its own weights
	# (e.g. self-play A/B between a candidate and a baseline profile). Empty =
	# the live default profile, preserving every existing caller's behaviour.
	if profile_path != "":
		_scorer = ScoringProfileScript.new(profile_path)
	else:
		_scorer = ScoringProfileScript.new()


func search(live_gs: GameState, ai_index: int, options: Dictionary = {}) -> Dictionary:
	_ai_index = ai_index
	_mode = str(options.get("mode", "main"))
	var top_n := int(options.get("top_n", DEFAULT_TOP_N))
	var beam_width := int(options.get("beam_width", DEFAULT_BEAM_WIDTH))
	var node_budget := int(options.get("node_budget", DEFAULT_NODE_BUDGET))
	var time_budget_ms := int(options.get("time_budget_ms", DEFAULT_TIME_BUDGET_MS))
	var default_depth := DEFAULT_REACTIVE_MAX_DEPTH if _mode == "reactive" else DEFAULT_MAX_DEPTH
	var max_depth := int(options.get("max_depth", default_depth))
	var start_ms := Time.get_ticks_msec()
	var stopped_reason := "exhausted"
	var nodes_explored := 0
	var branches_expanded := 0
	var transposition_hits := 0
	var max_depth_reached := 0
	_sim.ai_index = ai_index
	# Track every simulated GameController (a Node, created via .new() and never
	# added to the tree) so they can be freed when the search ends. Without this,
	# each expanded branch leaks an orphan Node on every AI decision.
	var controllers: Array = []
	var root_sc: GameController = _sim.build_sim_controller(live_gs)
	if root_sc == null:
		return {"candidate_lines": [], "search_stats": _stats(0, 0, 0, 0, beam_width, 0, "clone_failed")}
	controllers.append(root_sc)
	var root_snapshot := ScoreModel.snapshot(root_sc.gs, _ai_index)
	var root_hash := ScoreModel.structural_hash(root_snapshot)
	# Ranker for the AI's own forced sub-decisions (e.g. which card to discard):
	# score the settled board of each option so quiescence can pick the best one
	# inline, without spawning beam branches that would dilute move diversity.
	var choice_ranker := func(cand_gs: GameState) -> float:
		var snap := ScoreModel.snapshot(cand_gs, _ai_index)
		var feats := ScoreModel.build_score_features(root_snapshot, snap, [])
		return float(_scorer.score_with_breakdown(feats)["score"])
	var seen: Dictionary = {}
	seen[root_hash] = true
	var frontier: Array = [{"sc": root_sc, "steps": [], "windows": [], "score": -INF, "breakdown": {}, "resolved_state": {}}]
	var leaves: Array = []
	while not frontier.is_empty():
		if nodes_explored >= node_budget:
			stopped_reason = "node_budget"
			break
		if Time.get_ticks_msec() - start_ms >= time_budget_ms:
			stopped_reason = "time_budget"
			break
		var next_frontier: Array = []
		for node in frontier:
			if nodes_explored >= node_budget:
				stopped_reason = "node_budget"
				break
			if Time.get_ticks_msec() - start_ms >= time_budget_ms:
				stopped_reason = "time_budget"
				break
			nodes_explored += 1
			max_depth_reached = maxi(max_depth_reached, node["steps"].size())
			var sc: GameController = node["sc"]
			var legal: Array = LegalMoveEnumerator.enumerate(sc.gs, ai_index)
			if legal.is_empty() or node["steps"].size() >= max_depth or sc.gs.game_over:
				_add_leaf(leaves, node, sc, root_snapshot)
				continue
			var expanded_any := false
			for cmd in legal:
				var cmd_str := str(cmd)
				branches_expanded += 1
				# Hash of the parent state — the state the AI is in when it issues
				# this scripted move. Recorded as the step's pre_hash so the live
				# executor can verify the world still matches before replaying it.
				var scripted_pre_hash := ScoreModel.structural_hash(ScoreModel.snapshot(sc.gs, _ai_index))
				var child: GameController = _sim.build_sim_controller(sc.gs)
				if child == null:
					continue
				controllers.append(child)
				child.submit_command(ai_index, cmd_str)
				if child.last_command_error:
					continue
				var child_windows: Array = []
				var ai_steps: Array = []
				_sim.advance_to_quiescence(child, cmd_str, child_windows, ai_steps, choice_ranker)
				var snap := ScoreModel.snapshot(child.gs, _ai_index)
				var hash := ScoreModel.structural_hash(snap)
				if seen.has(hash):
					transposition_hits += 1
					continue
				seen[hash] = true
				expanded_any = true
				var resolved := _sim.build_delta(root_snapshot, snap, child.gs)
				var steps: Array = node["steps"].duplicate(true)
				steps.append({
					"command": cmd_str, "context": "", "kind": "scripted",
					"pre_hash": scripted_pre_hash,
				})
				# Any auto-resolved AI sub-decisions (target choices, showdown /
				# chain passes) become explicit intermediate steps in the line.
				steps.append_array(ai_steps)
				var features := ScoreModel.build_score_features(root_snapshot, snap, steps)
				var scored := _scorer.score_with_breakdown(features)
				var windows: Array = node["windows"].duplicate(true)
				windows.append_array(child_windows)
				var child_node := {"sc": child, "steps": steps, "windows": windows, "score": scored["score"], "breakdown": scored["breakdown"], "resolved_state": resolved}
				if _is_leaf(cmd_str, child):
					_add_leaf(leaves, child_node, child, root_snapshot)
				else:
					next_frontier.append(child_node)
			if not expanded_any:
				_add_leaf(leaves, node, sc, root_snapshot)
		if stopped_reason in ["node_budget", "time_budget"]:
			break
		frontier = _best_nodes(next_frontier, beam_width)
	for node in frontier:
		_add_leaf(leaves, node, node["sc"], root_snapshot)
	var elapsed := Time.get_ticks_msec() - start_ms
	var candidate_lines := _build_candidate_lines(leaves, top_n)
	# Free every simulated controller Node now that candidate lines (built from
	# snapshots/deltas, not the controllers) are extracted.
	for sc in controllers:
		if is_instance_valid(sc):
			sc.free()
	return {"candidate_lines": candidate_lines, "search_stats": _stats(nodes_explored, branches_expanded, transposition_hits, max_depth_reached, beam_width, elapsed, stopped_reason)}


func _add_leaf(leaves: Array, node: Dictionary, sc: GameController, root_snapshot: Dictionary) -> void:
	var snap := ScoreModel.snapshot(sc.gs, _ai_index)
	var features := ScoreModel.build_score_features(root_snapshot, snap, node.get("steps", []))
	var scored := _scorer.score_with_breakdown(features)
	var leaf := node.duplicate(true)
	leaf["score"] = scored["score"]
	leaf["breakdown"] = scored["breakdown"]
	leaf["features"] = features
	leaf["resolved_state"] = _sim.build_delta(root_snapshot, snap, sc.gs)
	leaves.append(leaf)


# Decide whether a freshly expanded child terminates the line.
#   main:     stop at "end turn" or game over (plan the whole turn).
#   reactive: stop once the response window has resolved — the AI is no longer
#             obliged to act in a chain/showdown — or game over. This keeps a
#             reactive line scoped to the interference, instead of spilling into
#             full main-phase planning when the window resolves on the AI's turn.
func _is_leaf(cmd_str: String, child: GameController) -> bool:
	if child.gs.game_over:
		return true
	if _mode == "reactive":
		return not _ai_has_response_window(child.gs)
	return cmd_str == "end turn"


func _ai_has_response_window(gs: GameState) -> bool:
	if gs.is_closed_chain_state() and gs.priority_player_index == _ai_index:
		return true
	if gs.current_state == TurnStateMachine.State.SHOWDOWN_OPEN and gs.focus_player_index == _ai_index:
		return true
	return false


func _best_nodes(nodes: Array, beam_width: int) -> Array:
	nodes.sort_custom(func(a, b): return float(a.get("score", 0.0)) > float(b.get("score", 0.0)))
	return nodes.slice(0, mini(beam_width, nodes.size()))


func _build_candidate_lines(leaves: Array, top_n: int) -> Array:
	leaves.sort_custom(func(a, b): return float(a.get("score", 0.0)) > float(b.get("score", 0.0)))
	var out: Array = []
	var count := mini(top_n, leaves.size())
	for i in range(count):
		var leaf: Dictionary = leaves[i]
		var steps: Array = leaf.get("steps", [])
		var moves: Array = []
		var move_contexts: Array = []
		var pre_hashes: Array = []
		for step in steps:
			moves.append(step.get("command", ""))
			move_contexts.append({
				"context": step.get("context", ""),
				"kind": step.get("kind", "scripted"),
			})
			pre_hashes.append(step.get("pre_hash", ""))
		out.append({
			"line_id": "line-%d" % (i + 1),
			"moves": moves,
			"move_contexts": move_contexts,
			"expected_pre_hashes": pre_hashes,
			"score": float(leaf.get("score", 0.0)),
			"score_breakdown": leaf.get("breakdown", {}),
			"features": leaf.get("features", {}),
			"resolved_state": leaf.get("resolved_state", {}),
			"opponent_windows": leaf.get("windows", []),
		})
	return out


func _stats(nodes: int, branches: int, hits: int, depth: int, beam_width: int, elapsed: int, reason: String) -> Dictionary:
	return {"mode": _mode, "nodes_explored": nodes, "branches_expanded": branches, "transposition_hits": hits, "max_depth_reached": depth, "beam_width": beam_width, "elapsed_ms": elapsed, "stopped_reason": reason}
