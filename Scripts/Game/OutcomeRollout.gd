class_name OutcomeRollout
extends RefCounted

# Bounded multi-turn / reactive counterfactual tree.
# Composes TurnSearch per decision boundary + LineReplayer for state handoff.
# Scores / reports from the original analyzed seat's perspective.

const TurnSearchScript = preload("res://Scripts/Game/TurnSearch.gd")
const LineReplayerScript = preload("res://Scripts/Game/LineReplayer.gd")
const MoveSimulatorScript = preload("res://Scripts/Game/MoveSimulator.gd")
const ScoreModelScript = preload("res://Scripts/Game/ScoreModel.gd")
const ScoringProfileScript = preload("res://Scripts/Game/ScoringProfile.gd")

const DEFAULT_FUTURE_PLAYER_TURNS := 4
const HARD_CAP_FUTURE_PLAYER_TURNS := 6
const DEFAULT_FRONTIER_CAP := 24
const DEFAULT_GLOBAL_NODE_BUDGET := 10000
const DEFAULT_GLOBAL_TIME_MS := 30000
const DEFAULT_SEAT_TOP_N := 2
const DEFAULT_OPPONENT_TOP_N := 3
const DEFAULT_TURN_BEAM_WIDTH := 8
# Nested *spells* on a chain (hextech then smoke screen, …). Passes that just
# give priority back do not consume this — a normal chain is many passes.
const DEFAULT_REACTIVE_DEPTH_GUARD := 16
const DEFAULT_REACTIVE_PASS_STREAK := 24
# Extra same-seat searches allowed when a main-turn line did not reach end turn.
const MAX_TURN_CONTINUATIONS := 3

var _replayer: RefCounted = LineReplayerScript.new()
var _sim: RefCounted = MoveSimulatorScript.new()
var _perspective_seat: int = 0
var _profile_path: String = ""
var _overlay: Dictionary = {}
var _profile_by_seat: Dictionary = {}
var _root_snap: Dictionary = {}
var _prefer_horizon_depth := false


func search_rollout(live_gs: GameState, perspective_seat: int, options: Dictionary = {}) -> Dictionary:
	_perspective_seat = perspective_seat
	_profile_path = str(options.get("profile_path", ""))
	_overlay = options.get("overlay", {}) if options.get("overlay", null) is Dictionary else {}
	_profile_by_seat = options.get("profile_path_by_seat", {}) if options.get("profile_path_by_seat", null) is Dictionary else {}

	var future_turns := clampi(
		int(options.get("future_player_turns", DEFAULT_FUTURE_PLAYER_TURNS)),
		1,
		HARD_CAP_FUTURE_PLAYER_TURNS
	)
	# Absolute game turn to finish (gs.turn_number). 0 = use future_player_turns only.
	var until_turn := int(options.get("until_turn_number", options.get("until_turn", 0)))
	_prefer_horizon_depth = until_turn > 0
	var frontier_cap := int(options.get("frontier_cap", DEFAULT_FRONTIER_CAP))
	var global_node_budget := int(options.get("global_node_budget", DEFAULT_GLOBAL_NODE_BUDGET))
	var global_time_ms := int(options.get("global_time_ms", DEFAULT_GLOBAL_TIME_MS))
	# Until-turn-N chains eat the 30s default before the last main turn is
	# even searched. Scale clock with how many player-turns we still owe.
	if until_turn > 0:
		var span := maxi(1, until_turn - int(live_gs.turn_number) + 1)
		global_time_ms = maxi(global_time_ms, mini(180000, 20000 * span))
	var seat_top_n := int(options.get("seat_top_n", DEFAULT_SEAT_TOP_N))
	var opponent_top_n := int(options.get("opponent_top_n", DEFAULT_OPPONENT_TOP_N))
	var turn_beam_width := int(options.get("turn_beam_width", DEFAULT_TURN_BEAM_WIDTH))
	var per_turn_node := int(options.get("per_turn_node_budget", 400))
	var per_turn_time := int(options.get("per_turn_time_budget_ms", 800))
	var per_turn_depth := int(options.get("per_turn_max_depth", 12))
	var reactive_depth_guard := int(options.get("reactive_depth_guard", DEFAULT_REACTIVE_DEPTH_GUARD))
	var reactive_pass_streak := int(options.get("reactive_pass_streak", DEFAULT_REACTIVE_PASS_STREAK))

	var start_ms := Time.get_ticks_msec()
	var nodes_used := 0
	var searches := 0
	var truncated := false
	var stop_reason := "horizon"

	var root_snap := ScoreModelScript.snapshot(live_gs, perspective_seat)
	_root_snap = root_snap
	var root_hash := ScoreModelScript.structural_hash(root_snap)
	var roots: Array = options.get("roots", [])
	if roots.is_empty() and options.has("seed_moves"):
		roots = [{"line_id": "seed", "moves": options.get("seed_moves", []), "source": "seed"}]
	if roots.is_empty():
		# Search the analyzed seat once to invent roots when none supplied.
		var boot := _search_seat(live_gs, perspective_seat, {
			"mode": "main",
			"top_n": maxi(seat_top_n + 1, 5),
			"beam_width": turn_beam_width,
			"node_budget": per_turn_node,
			"time_budget_ms": per_turn_time,
			"max_depth": per_turn_depth,
		})
		nodes_used += int((boot.get("search_stats") or {}).get("nodes_explored", 0))
		searches += 1
		for line in boot.get("candidate_lines", []):
			roots.append({
				"line_id": str(line.get("line_id", "line")),
				"moves": line.get("moves", []),
				"source": "offline_search",
				"score": line.get("score", 0.0),
			})

	# Frontier nodes hold live GameState clones for expansion; freed on exit.
	var frontier: Array = []
	var leaves: Array = []
	var tree_nodes: Array = []
	var next_id := 0
	var controllers_to_free: Array = []

	for root in roots:
		var moves: Array = root.get("moves", [])
		var line_id := str(root.get("line_id", "root-%d" % next_id))
		var source := str(root.get("source", "root"))
		var replay: Dictionary = _replayer.replay_line(live_gs, moves, perspective_seat, {
			"stop_at_opponent": true,
		})
		if not bool(replay.get("ok", false)) and replay.get("gs") == null:
			tree_nodes.append({
				"node_id": "n%d" % next_id,
				"parent_id": "",
				"root_line_id": line_id,
				"source": source,
				"seat": perspective_seat,
				"depth_player_turns": 0,
				"reactive_depth": 0,
				"moves": moves,
				"applied": [],
				"complete": false,
				"terminal_reason": str(replay.get("error", "replay_failed")),
				"is_leaf": true,
			})
			next_id += 1
			continue
		var node_gs: GameState = replay["gs"]
		var node := {
			"id": "n%d" % next_id,
			"parent_id": "",
			"root_line_id": line_id,
			"source": source,
			"gs": node_gs,
			"seat": perspective_seat,
			"depth_player_turns": 0,
			"reactive_depth": 0,
			"pass_streak": 0,
			"path_segments": [{
				"seat": perspective_seat,
				"line_id": line_id,
				"moves": replay.get("applied", moves),
				"remaining": replay.get("remaining", []),
				"boundary": replay.get("boundary", {}),
				"kind": "root",
				"score": float(root.get("score", 0.0)),
				"policy_rank": 1,
			}],
			"applied_root_moves": replay.get("applied", moves),
			"remaining_root_moves": replay.get("remaining", []),
			"boundary": replay.get("boundary", {}),
			"complete": bool(replay.get("complete", false)),
			"terminal_reason": str(replay.get("terminal_reason", "")),
			"search_state": replay.get("search_state", {}),
			"score": float(root.get("score", 0.0)),
			"acting_score": float(root.get("score", 0.0)),
			"continuation_count": 0,
			"opp_policy_rank": 1,
			"our_policy_rank": 1,
			"preserve_root": true,
		}
		next_id += 1
		_emit_tree_node(tree_nodes, node, false)
		if node_gs.game_over or (
			bool(replay.get("complete", false))
			and str(replay.get("terminal_reason", "")) == "game_over"
		):
			_finalize_leaf(leaves, node, root_snap)
			continue
		frontier.append(node)

	while not frontier.is_empty():
		if nodes_used >= global_node_budget:
			truncated = true
			stop_reason = "node_budget"
			break
		if Time.get_ticks_msec() - start_ms >= global_time_ms:
			truncated = true
			stop_reason = "time_budget"
			break

		# Expand closer-to-horizon / policy nodes first so leftover time
		# finishes turn N instead of re-searching early high-score stubs.
		frontier.sort_custom(_cmp_retain_node)

		var next_frontier: Array = []
		for node in frontier:
			if nodes_used >= global_node_budget or Time.get_ticks_msec() - start_ms >= global_time_ms:
				truncated = true
				stop_reason = "node_budget" if nodes_used >= global_node_budget else "time_budget"
				next_frontier.append(node)
				continue

			var gs: GameState = node["gs"]
			if gs == null or gs.game_over:
				_finalize_leaf(leaves, node, root_snap)
				continue

			var boundary: Dictionary = node.get("boundary", {})
			if boundary.is_empty():
				boundary = _sim.describe_decision_boundary(gs, _perspective_seat)
				node["boundary"] = boundary

			var acting := int(boundary.get("acting_seat", gs.turn_player_index))
			var kind := str(boundary.get("kind", "main_turn"))
			if kind == "none":
				# Nothing forced — if it's someone's main turn, search that seat.
				acting = gs.turn_player_index
				kind = "main_turn"
				boundary = {"kind": kind, "acting_seat": acting}
				node["boundary"] = boundary

			if _horizon_reached(gs, node, kind, future_turns, until_turn):
				_finalize_leaf(leaves, node, root_snap)
				continue

			if kind in ["chain", "showdown", "prompt"]:
				if int(node.get("reactive_depth", 0)) >= reactive_depth_guard:
					node["terminal_reason"] = "reactive_depth_guard"
					_finalize_leaf(leaves, node, root_snap)
					continue
				if int(node.get("pass_streak", 0)) >= reactive_pass_streak:
					node["terminal_reason"] = "reactive_pass_streak"
					_finalize_leaf(leaves, node, root_snap)
					continue

			var top_n := opponent_top_n if acting != _perspective_seat else seat_top_n
			var mode := "reactive" if kind in ["chain", "showdown", "prompt"] else "main"
			# Ask TurnSearch for extra leaves so complete end-turn lines survive
			# filtering; rank complete ahead of high-scoring fragments.
			var search_top_n := maxi(top_n * 3, 8) if mode == "main" else top_n
			var search_opts := {
				"mode": mode,
				"top_n": search_top_n,
				"prefer_complete": mode == "main",
				"beam_width": turn_beam_width,
				"node_budget": per_turn_node,
				"time_budget_ms": per_turn_time,
				"max_depth": per_turn_depth if mode == "main" else mini(per_turn_depth, 6),
			}
			# If this node still carries a stale root suffix for the same seat and
			# no intervening reaction, prefer re-searching (policy) rather than
			# blindly replaying the remaining historical commands.
			var search_payload = _search_seat(gs, acting, search_opts)
			searches += 1
			var search_stats: Dictionary = {}
			var lines: Array = []
			if search_payload is Dictionary:
				var raw_stats = search_payload.get("search_stats", {})
				if raw_stats is Dictionary:
					search_stats = raw_stats
				var raw_lines = search_payload.get("candidate_lines", [])
				if raw_lines is Array:
					lines = raw_lines
			nodes_used += int(search_stats.get("nodes_explored", 0))

			var picked: Dictionary = _select_expandable_lines(
				lines, mode, top_n, int(node.get("continuation_count", 0))
			)
			var usable: Array = picked.get("expand", [])
			var continuations: Array = picked.get("continue", [])
			if usable.is_empty() and continuations.is_empty():
				node["terminal_reason"] = str(picked.get("empty_reason", "no_legal_lines"))
				_finalize_leaf(leaves, node, root_snap)
				continue

			var expanded_any := false
			var next_rank := 1
			for line in usable:
				var stamped: Dictionary = (line as Dictionary).duplicate(true)
				stamped["policy_rank"] = _line_policy_rank(stamped, next_rank)
				next_rank += 1
				var child := _expand_line(node, stamped, acting, kind, mode, next_id, _root_snap)
				next_id += 1
				if child.is_empty():
					continue
				expanded_any = true
				_emit_tree_node(tree_nodes, child, bool(child.get("is_leaf", false)))
				if bool(child.get("is_leaf", false)):
					_finalize_leaf(leaves, child, root_snap)
				else:
					next_frontier.append(child)
			for line in continuations:
				var stamped: Dictionary = (line as Dictionary).duplicate(true)
				stamped["policy_rank"] = _line_policy_rank(stamped, next_rank)
				next_rank += 1
				var child := _expand_line(node, stamped, acting, kind, mode, next_id, _root_snap)
				next_id += 1
				if child.is_empty():
					continue
				child["is_leaf"] = false
				var child_boundary: Dictionary = child.get("boundary", {})
				var still_same_seat := (
					int(child_boundary.get("acting_seat", acting)) == acting
					and str(child_boundary.get("kind", "main_turn")) == "main_turn"
				)
				if still_same_seat:
					child["continuation_count"] = int(node.get("continuation_count", 0)) + 1
				else:
					child["continuation_count"] = 0
				child["terminal_reason"] = "turn_continuation"
				expanded_any = true
				_emit_tree_node(tree_nodes, child, false)
				next_frontier.append(child)
			if not expanded_any:
				node["terminal_reason"] = "expand_failed"
				_finalize_leaf(leaves, node, root_snap)

		# Free GameStates of nodes that leave the frontier (leaves keep gs until end).
		for node in frontier:
			var still := false
			for n2 in next_frontier:
				if n2.get("id") == node.get("id"):
					still = true
					break
			if not still:
				controllers_to_free.append(node)

		frontier = _prune_frontier(next_frontier, frontier_cap, leaves, root_snap)
		if frontier.is_empty() and stop_reason == "horizon":
			stop_reason = "exhausted"

	# Remaining frontier becomes truncated leaves.
	for node in frontier:
		node["terminal_reason"] = stop_reason if truncated else "horizon"
		_finalize_leaf(leaves, node, root_snap)

	var elapsed := Time.get_ticks_msec() - start_ms
	var paths := _build_paths(leaves, root_snap)
	var checkpoints := _collect_checkpoints(leaves)

	# Drop live GameState refs from serialized output; free clones.
	for node in leaves + controllers_to_free:
		var gs_ref = node.get("gs")
		node["gs"] = null
		# GameState is RefCounted — clearing refs is enough.

	return {
		"ok": true,
		"legal": true,
		"root_state_hash": root_hash,
		"perspective_seat": perspective_seat,
		"horizon": "multi_turn",
		"future_player_turns": future_turns,
		"until_turn_number": until_turn,
		"opponent_policy": "oracle",
		"information_mode": "oracle_hidden_state",
		"truncated": truncated,
		"stop_reason": stop_reason,
		"rollout_tree": {
			"nodes": tree_nodes,
			"paths": paths,
			"checkpoints": checkpoints,
		},
		"principal_variations": paths,
		"candidate_lines": paths,
		"search_stats": {
			"nodes_explored": nodes_used,
			"searches": searches,
			"leaves": leaves.size(),
			"tree_nodes": tree_nodes.size(),
			"elapsed_ms": elapsed,
			"stopped_reason": stop_reason,
			"frontier_cap": frontier_cap,
			"global_time_ms": global_time_ms,
			"future_player_turns": future_turns,
			"until_turn_number": until_turn,
		},
		"assumptions": {
			"horizon": "multi_turn",
			"opponent_policy": "oracle",
			"information_mode": "oracle_hidden_state",
			"future_player_turns": future_turns,
			"until_turn_number": until_turn,
			"policy_bounded": true,
		},
	}


func _search_seat(gs: GameState, seat: int, options: Dictionary) -> Dictionary:
	var profile := _profile_path
	if _profile_by_seat.has(str(seat)):
		profile = str(_profile_by_seat[str(seat)])
	elif _profile_by_seat.has(seat):
		profile = str(_profile_by_seat[seat])
	var overlay := _overlay if seat == _perspective_seat else {}
	var searcher = TurnSearchScript.new(profile, overlay)
	return searcher.search(gs, seat, options)


func _expand_line(
	parent: Dictionary,
	line: Dictionary,
	acting: int,
	boundary_kind: String,
	mode: String,
	next_id: int,
	root_snap: Dictionary,
) -> Dictionary:
	var parent_gs: GameState = parent.get("gs")
	if parent_gs == null:
		return {}
	var moves: Array = line.get("moves", [])
	# TurnSearch "quiescence" with no commands means this seat declines to act.
	# On a chain that is a pass — replaying nothing leaves the same boundary
	# and spins until reactive_depth_guard.
	if mode == "reactive" and _line_moves({"moves": moves}).is_empty():
		moves = ["pass"]
	var replay: Dictionary = _replayer.replay_line(parent_gs, moves, acting, {
		"stop_at_opponent": true,
	})
	if replay.get("gs") == null and not bool(replay.get("ok", false)):
		return {}

	var child_gs: GameState = replay["gs"]
	var child_boundary: Dictionary = replay.get("boundary", {})
	var turn_delta := 0
	if mode == "main" and str(replay.get("terminal_reason", "")) in ["end_turn", "game_over"]:
		turn_delta = 1
	elif mode == "main" and bool(replay.get("complete", false)) and str(line.get("terminal_reason", "")) == "end_turn":
		turn_delta = 1

	var depth := int(parent.get("depth_player_turns", 0)) + turn_delta
	var reactive_depth := int(parent.get("reactive_depth", 0))
	var pass_streak := int(parent.get("pass_streak", 0))
	if mode == "reactive":
		# Nested spells consume the guard; priority passes are normal chain
		# resolution and must not abort a line before the window closes.
		if _is_skip_only_line({"moves": replay.get("applied", moves)}):
			pass_streak += 1
		else:
			reactive_depth += 1
			pass_streak = 0
	else:
		reactive_depth = 0
		pass_streak = 0

	var policy_rank := _line_policy_rank(line, 1)
	var segment := {
		"seat": acting,
		"line_id": str(line.get("line_id", "")),
		"moves": replay.get("applied", moves),
		"remaining": replay.get("remaining", []),
		"boundary": child_boundary,
		"kind": mode,
		"score": float(line.get("score", 0.0)),
		"policy_rank": policy_rank,
		"terminal_reason": str(replay.get("terminal_reason", line.get("terminal_reason", ""))),
		"complete": bool(replay.get("complete", line.get("complete", false))),
		"search_state": replay.get("search_state", line.get("search_state", {})),
	}
	var path_segments: Array = parent.get("path_segments", []).duplicate(true)
	path_segments.append(segment)

	var is_leaf := false
	var terminal_reason := str(segment.get("terminal_reason", ""))
	if child_gs != null and child_gs.game_over:
		is_leaf = true
		terminal_reason = "game_over"
	elif str(replay.get("stopped_reason", "")) == "decision_boundary":
		is_leaf = false
	elif turn_delta == 1 and depth >= 0:
		# After a completed main turn, continue unless caller decides otherwise.
		is_leaf = false
		# Mark checkpoint on the segment.
		segment["checkpoint"] = _checkpoint(child_gs, depth, acting, segment)
	elif mode == "reactive" and bool(segment.get("complete", false)):
		is_leaf = false

	# If replay stopped mid-line with remaining moves for the SAME seat, drop
	# the stale suffix — next expansion re-searches from the branched state.
	var opp_rank := int(parent.get("opp_policy_rank", 1))
	var our_rank := int(parent.get("our_policy_rank", 1))
	if acting != _perspective_seat:
		opp_rank = maxi(opp_rank, policy_rank)
	else:
		our_rank = maxi(our_rank, policy_rank)
	var child := {
		"id": "n%d" % next_id,
		"parent_id": str(parent.get("id", "")),
		"root_line_id": str(parent.get("root_line_id", "")),
		"source": str(parent.get("source", "")),
		"gs": child_gs,
		"seat": acting,
		"depth_player_turns": depth,
		"reactive_depth": reactive_depth,
		"pass_streak": pass_streak,
		"path_segments": path_segments,
		"boundary": child_boundary,
		"complete": bool(segment.get("complete", false)),
		"terminal_reason": terminal_reason,
		"search_state": segment.get("search_state", {}),
		"score": _score_from_perspective(child_gs, root_snap),
		"acting_score": float(line.get("score", 0.0)),
		"continuation_count": int(parent.get("continuation_count", 0)),
		"opp_policy_rank": opp_rank,
		"our_policy_rank": our_rank,
		"preserve_root": bool(parent.get("preserve_root", false)),
		"is_leaf": is_leaf,
		"checkpoint": segment.get("checkpoint", {}),
	}
	# If remaining moves exist after an opponent boundary, do not keep them —
	# policy re-search replaces the stale suffix.
	return child


func _child_from_line(
	parent: Dictionary,
	line: Dictionary,
	acting: int,
	boundary_kind: String,
	mode: String,
	next_id: int,
	force_leaf: bool,
) -> Dictionary:
	var child := _expand_line(parent, line, acting, boundary_kind, mode, next_id, _root_snap)
	if child.is_empty():
		return {
			"id": "n%d" % next_id,
			"parent_id": str(parent.get("id", "")),
			"root_line_id": str(parent.get("root_line_id", "")),
			"source": str(parent.get("source", "")),
			"gs": null,
			"seat": acting,
			"depth_player_turns": int(parent.get("depth_player_turns", 0)),
			"reactive_depth": int(parent.get("reactive_depth", 0)),
			"path_segments": parent.get("path_segments", []),
			"boundary": parent.get("boundary", {}),
			"complete": false,
			"terminal_reason": "expand_failed",
			"search_state": line.get("search_state", {}),
			"score": float(line.get("score", 0.0)),
			"preserve_root": bool(parent.get("preserve_root", false)),
			"is_leaf": true,
		}
	if force_leaf:
		child["is_leaf"] = true
	return child


func _checkpoint(gs: GameState, depth: int, acting: int, segment: Dictionary) -> Dictionary:
	if gs == null:
		return {}
	var snap := ScoreModelScript.snapshot(gs, _perspective_seat)
	var step_dicts: Array = []
	for m in segment.get("moves", []):
		if m is Dictionary:
			step_dicts.append(m)
		else:
			step_dicts.append({"command": str(m), "kind": "scripted"})
	var features := ScoreModelScript.build_score_features(_root_snap if not _root_snap.is_empty() else snap, snap, step_dicts)
	return {
		"depth_player_turns": depth,
		"acting_seat": acting,
		"turn_number": gs.turn_number,
		"turn_player_index": gs.turn_player_index,
		"game_over": gs.game_over,
		"winner_index": gs.winner_index,
		"state_hash": ScoreModelScript.structural_hash(snap),
		"search_state": ScoreModelScript.build_search_state(snap, features, step_dicts),
		"complete": bool(segment.get("complete", false)),
		"terminal_reason": str(segment.get("terminal_reason", "")),
	}


func _score_from_perspective(gs: GameState, root_snap: Dictionary) -> float:
	if gs == null:
		return -INF
	var snap := ScoreModelScript.snapshot(gs, _perspective_seat)
	var features := ScoreModelScript.build_score_features(root_snap, snap, [])
	var profile_path := _profile_path
	if profile_path == "":
		profile_path = "res://Data/AI/scoring_profile.json"
	var scorer = ScoringProfileScript.new(profile_path)
	if not _overlay.is_empty():
		scorer.apply_overlay(_overlay)
	return float(scorer.score_with_breakdown(features).get("score", 0.0))


func _finalize_leaf(leaves: Array, node: Dictionary, root_snap: Dictionary) -> void:
	node["is_leaf"] = true
	if node.get("gs") != null and float(node.get("score", -INF)) == -INF:
		node["score"] = _score_from_perspective(node["gs"], root_snap)
	if node.get("gs") != null and (node.get("checkpoint") == null or (node.get("checkpoint") is Dictionary and node["checkpoint"].is_empty())):
		node["checkpoint"] = _checkpoint(
			node["gs"],
			int(node.get("depth_player_turns", 0)),
			int(node.get("seat", _perspective_seat)),
			{"moves": [], "complete": true, "terminal_reason": node.get("terminal_reason", "")},
		)
	leaves.append(node)


func _emit_tree_node(tree_nodes: Array, node: Dictionary, is_leaf: bool) -> void:
	tree_nodes.append({
		"node_id": str(node.get("id", "")),
		"parent_id": str(node.get("parent_id", "")),
		"root_line_id": str(node.get("root_line_id", "")),
		"source": str(node.get("source", "")),
		"seat": int(node.get("seat", -1)),
		"depth_player_turns": int(node.get("depth_player_turns", 0)),
		"reactive_depth": int(node.get("reactive_depth", 0)),
		"boundary": node.get("boundary", {}),
		"path_segments": node.get("path_segments", []),
		"complete": bool(node.get("complete", false)),
		"terminal_reason": str(node.get("terminal_reason", "")),
		"score": float(node.get("score", 0.0)),
		"search_state": node.get("search_state", {}),
		"checkpoint": node.get("checkpoint", {}),
		"is_leaf": is_leaf or bool(node.get("is_leaf", false)),
	})


func _select_expandable_lines(lines: Array, mode: String, top_n: int, continuation_count: int) -> Dictionary:
	if mode != "main":
		var reactive: Array = []
		for line in lines:
			if typeof(line) == TYPE_DICTIONARY:
				reactive.append(line)
		if reactive.size() > top_n:
			reactive = reactive.slice(0, top_n)
		return {"expand": reactive, "continue": [], "empty_reason": "no_legal_lines"}

	var complete_lines: Array = []
	var incomplete_lines: Array = []
	for line in lines:
		if typeof(line) != TYPE_DICTIONARY:
			continue
		if _is_complete_main_line(line):
			complete_lines.append(line)
		elif not _line_moves(line).is_empty():
			incomplete_lines.append(line)

	var expand: Array = []
	for line in complete_lines:
		if expand.size() >= top_n:
			break
		expand.append(line)

	var continuations: Array = []
	var can_continue := continuation_count < MAX_TURN_CONTINUATIONS
	# If the only complete lines are pass/end-turn, still keep a real play
	# fragment so the opponent cannot "skip" just because skip completed first.
	var only_skips := not expand.is_empty()
	for line in expand:
		if not _is_skip_only_line(line):
			only_skips = false
			break
	if can_continue:
		var need := top_n - expand.size()
		if only_skips:
			need = maxi(need, mini(1, incomplete_lines.size()))
		for line in incomplete_lines:
			if need <= 0:
				break
			if _is_skip_only_line(line):
				continue
			continuations.append(line)
			need -= 1

	if expand.is_empty() and continuations.is_empty():
		if not incomplete_lines.is_empty() and can_continue:
			continuations.append(incomplete_lines[0])
		elif not incomplete_lines.is_empty():
			return {"expand": [], "continue": [], "empty_reason": "incomplete_budget_leaf"}
		else:
			return {"expand": [], "continue": [], "empty_reason": "no_legal_lines"}
	return {"expand": expand, "continue": continuations, "empty_reason": ""}


func _horizon_reached(
	gs: GameState,
	node: Dictionary,
	kind: String,
	future_turns: int,
	until_turn: int,
) -> bool:
	if kind != "main_turn":
		return false
	if until_turn > 0:
		# Turn N has ended once the engine has started a later turn's main.
		return gs.turn_number > until_turn
	return int(node.get("depth_player_turns", 0)) >= future_turns


func _is_complete_main_line(line: Dictionary) -> bool:
	if not bool(line.get("complete", false)):
		return false
	return str(line.get("terminal_reason", "")) in ["end_turn", "game_over"]


func _line_moves(line: Dictionary) -> Array:
	var moves: Array = []
	for m in line.get("moves", []):
		var s := str(m).strip_edges()
		if s != "":
			moves.append(s)
	return moves


func _is_skip_only_line(line: Dictionary) -> bool:
	var seen_action := false
	for m in _line_moves(line):
		if m == "end turn" or m == "pass":
			continue
		if m.begins_with("choose "):
			continue
		seen_action = true
		break
	return not seen_action


func _line_policy_rank(line: Dictionary, fallback: int) -> int:
	if line.has("policy_rank"):
		var explicit := int(line.get("policy_rank", 0))
		if explicit > 0:
			return explicit
	var lid := str(line.get("line_id", ""))
	if lid.begins_with("line-"):
		var n := lid.substr(5).to_int()
		if n > 0:
			return n
	return maxi(fallback, 1)


func _prune_frontier(nodes: Array, cap: int, leaves: Array, root_snap: Dictionary) -> Array:
	if nodes.size() <= cap:
		return nodes
	# Stratified: keep at least one node per root_line_id when possible.
	# Opponent-to-move nodes are ranked by *their* TurnSearch score so a
	# cooperative skip cannot crowd out the opponent's real replies.
	var by_root: Dictionary = {}
	for n in nodes:
		var rid := str(n.get("root_line_id", ""))
		if not by_root.has(rid):
			by_root[rid] = []
		by_root[rid].append(n)
	var kept: Array = []
	var kept_ids: Dictionary = {}
	for rid in by_root.keys():
		var group: Array = by_root[rid]
		group.sort_custom(_cmp_retain_node)
		var pick = group[0]
		kept.append(pick)
		kept_ids[str(pick.get("id", ""))] = true
		if kept.size() >= cap:
			return kept
	var rest: Array = []
	for n in nodes:
		if not kept_ids.has(str(n.get("id", ""))):
			rest.append(n)
	rest.sort_custom(_cmp_retain_node)
	for n in rest:
		if kept.size() >= cap:
			n["terminal_reason"] = "frontier_pruned"
			_finalize_leaf(leaves, n, root_snap)
			continue
		kept.append(n)
	return kept


func _cmp_retain_node(a: Dictionary, b: Dictionary) -> bool:
	# Keep paths where the opponent played *their* best lines, not lines that
	# inflate the analyzed seat's score. Rank 1 = that seat's TurnSearch best.
	var ao := int(a.get("opp_policy_rank", 99))
	var bo := int(b.get("opp_policy_rank", 99))
	if ao != bo:
		return ao < bo
	var au := int(a.get("our_policy_rank", 99))
	var bu := int(b.get("our_policy_rank", 99))
	if au != bu:
		return au < bu
	# Until-turn-N: a shallow +13 at turn 6 is not better than a deeper line
	# that can actually finish the requested turn.
	if _prefer_horizon_depth:
		var ad := int(a.get("depth_player_turns", 0))
		var bd := int(b.get("depth_player_turns", 0))
		if ad != bd:
			return ad > bd
	return float(a.get("score", 0.0)) > float(b.get("score", 0.0))


func _build_paths(leaves: Array, root_snap: Dictionary) -> Array:
	var out: Array = []
	var sorted_leaves := leaves.duplicate()
	sorted_leaves.sort_custom(_cmp_retain_node)
	for i in range(sorted_leaves.size()):
		var leaf: Dictionary = sorted_leaves[i]
		var segments: Array = leaf.get("path_segments", [])
		var flat_moves: Array = []
		for seg in segments:
			for m in seg.get("moves", []):
				flat_moves.append(str(m))
		var opp_rank := int(leaf.get("opp_policy_rank", 1))
		var our_rank := int(leaf.get("our_policy_rank", 1))
		var cp: Dictionary = leaf.get("checkpoint", {}) if leaf.get("checkpoint") is Dictionary else {}
		out.append({
			"line_id": "pv-%d" % (i + 1),
			"root_line_id": str(leaf.get("root_line_id", "")),
			"source": str(leaf.get("source", "")),
			"score": float(leaf.get("score", 0.0)),
			"moves": flat_moves,
			"path_segments": segments,
			"depth_player_turns": int(leaf.get("depth_player_turns", 0)),
			"turn_number": int(cp.get("turn_number", 0)),
			"terminal_reason": str(leaf.get("terminal_reason", "")),
			"complete": bool(leaf.get("complete", false)) or str(leaf.get("terminal_reason", "")) == "game_over",
			"search_state": leaf.get("search_state", {}),
			"checkpoint": leaf.get("checkpoint", {}),
			"node_id": str(leaf.get("id", "")),
			"opp_policy_rank": opp_rank,
			"our_policy_rank": our_rank,
			"is_policy_pv": opp_rank <= 1 and our_rank <= 1,
		})
	return out


func _collect_checkpoints(leaves: Array) -> Array:
	var out: Array = []
	var seen: Dictionary = {}
	for leaf in leaves:
		for seg in leaf.get("path_segments", []):
			var cp = seg.get("checkpoint", {})
			if cp is Dictionary and not cp.is_empty():
				var key := str(cp.get("state_hash", "")) + "|" + str(cp.get("depth_player_turns", 0))
				if seen.has(key):
					continue
				seen[key] = true
				out.append(cp)
		var leaf_cp = leaf.get("checkpoint", {})
		if leaf_cp is Dictionary and not leaf_cp.is_empty():
			var key2 := str(leaf_cp.get("state_hash", "")) + "|" + str(leaf_cp.get("depth_player_turns", 0))
			if not seen.has(key2):
				seen[key2] = true
				out.append(leaf_cp)
	return out
