class_name LineRiskProbe
extends RefCounted

const LineReplayerScript = preload("res://Scripts/Game/LineReplayer.gd")
const MoveSimulatorScript = preload("res://Scripts/Game/MoveSimulator.gd")
const ScoreModelScript = preload("res://Scripts/Game/ScoreModel.gd")
const ScoringProfileScript = preload("res://Scripts/Game/ScoringProfile.gd")
const TurnSearchScript = preload("res://Scripts/Game/TurnSearch.gd")
const CardLoaderScript = preload("res://Scripts/Data/CardLoader.gd")
const LegalMoveEnumeratorScript = preload("res://Scripts/AI/LegalMoveEnumerator.gd")


func annotate_lines(
	live_gs: GameState,
	seat: int,
	lines: Array,
	options: Dictionary = {},
) -> Array:
	var out: Array = []
	if live_gs == null or lines.is_empty():
		return lines.duplicate(true)
	var start_ms := Time.get_ticks_msec()
	var budget_ms := int(options.get("budget_ms", 350))
	var profile_path := str(options.get("profile_path", ""))
	var prior_data: Dictionary = options.get("reaction_priors", {})
	var scorer := ScoringProfileScript.new(profile_path)

	var by_cluster: Dictionary = {}
	for i in range(lines.size()):
		var line: Dictionary = lines[i]
		var key := str(line.get("cluster_key", ""))
		if key == "":
			key = str(i)
		if not by_cluster.has(key):
			by_cluster[key] = []
		by_cluster[key].append(i)

	var cluster_risk: Dictionary = {}
	for key in by_cluster.keys():
		if Time.get_ticks_msec() - start_ms >= budget_ms:
			break
		var idxs: Array = by_cluster[key]
		if idxs.is_empty():
			continue
		var rep: Dictionary = lines[int(idxs[0])]
		var rr = _risk_for_line(live_gs, seat, rep, scorer, prior_data, start_ms, budget_ms)
		cluster_risk[key] = rr

	for i in range(lines.size()):
		var line: Dictionary = (lines[i] as Dictionary).duplicate(true)
		var key := str(line.get("cluster_key", ""))
		if key == "":
			key = str(i)
		if cluster_risk.has(key):
			line["risk"] = cluster_risk[key]
		out.append(line)
	return out


func expand_risk(
	live_gs: GameState,
	seat: int,
	request: Dictionary,
	profile_path: String = "",
) -> Dictionary:
	var line: Dictionary = request.get("line", {})
	if line.is_empty():
		return {"ok": false, "error": "missing_line"}
	var priors: Dictionary = request.get("reaction_priors", {})
	var forced_card_id := str(request.get("card_id", ""))
	var scorer := ScoringProfileScript.new(profile_path)
	var rr: Dictionary = _risk_for_line(
		live_gs,
		seat,
		line,
		scorer,
		priors,
		Time.get_ticks_msec(),
		int(request.get("budget_ms", 300)),
		true,
		forced_card_id,
	)
	return {
		"ok": true,
		"line_id": str(line.get("line_id", "")),
		"risk": rr,
		"source": "live_engine",
	}


func _risk_for_line(
	live_gs: GameState,
	seat: int,
	line: Dictionary,
	scorer: RefCounted,
	prior_data: Dictionary,
	start_ms: int,
	budget_ms: int,
	with_recapture: bool = false,
	forced_card_id: String = "",
) -> Dictionary:
	var windows: Array = line.get("opponent_windows", [])
	if windows.is_empty():
		return {"threats": [], "risk_worst": 0.0, "risk_expected": 0.0, "can_recapture": false, "needs_recapture": false}
	var moves: Array = line.get("moves", [])
	var threats: Array = []
	if forced_card_id != "":
		threats = [{"card_id": forced_card_id, "timing": "action_or_reaction", "p_in_hand": 1.0}]
	else:
		threats = _build_threat_catalog(live_gs, seat, windows, prior_data)
	if threats.is_empty():
		return {"threats": [], "risk_worst": 0.0, "risk_expected": 0.0, "can_recapture": false, "needs_recapture": false}
	threats.sort_custom(func(a, b): return float(a.get("p_in_hand", 0.0)) > float(b.get("p_in_hand", 0.0)))
	var tested: Array = []
	var skipped: Array = []
	var scan_k := mini(8, threats.size())
	var risk_worst := 0.0
	var risk_expected := 0.0
	var can_recapture := false
	var needs_recapture := false
	for i in range(scan_k):
		if tested.size() >= 3:
			break
		if Time.get_ticks_msec() - start_ms >= budget_ms:
			break
		var t: Dictionary = threats[i]
		var evald := _evaluate_threat(live_gs, seat, moves, windows, t, scorer, with_recapture)
		if _is_skipped_threat(evald):
			skipped.append({
				"card_id": str(evald.get("card_id", t.get("card_id", ""))),
				"reason": str(evald.get("skip_reason", evald.get("note", "not_legal"))),
			})
			continue
		tested.append(evald)
		var d := float(evald.get("window_delta", 0.0))
		risk_worst = maxf(risk_worst, d)
		risk_expected += d * float(evald.get("p_in_hand", 0.0))
		can_recapture = can_recapture or bool(evald.get("can_recapture", false))
		needs_recapture = needs_recapture or bool(evald.get("plan_broken", false))
	return {
		"threats": tested,
		"skipped": skipped,
		"risk_worst": risk_worst,
		"risk_expected": risk_expected,
		"can_recapture": can_recapture,
		"needs_recapture": needs_recapture,
		"catalog_note": "belief_hidden_state_assumed_one_card",
		"information_mode": "belief_hidden_state",
	}


func _is_skipped_threat(evald: Dictionary) -> bool:
	if str(evald.get("note", "")) == "threat_not_legal_in_any_window":
		return true
	var reason := str(evald.get("skip_reason", ""))
	return reason != "" and not evald.has("window_after_move")


func _evaluate_threat(
	live_gs: GameState,
	seat: int,
	moves: Array,
	windows: Array,
	threat: Dictionary,
	scorer: RefCounted,
	with_recapture: bool,
) -> Dictionary:
	var best: Dictionary = {}
	var best_delta := -INF
	var last_skip := "no_matching_window"
	for wi in range(windows.size()):
		var window: Dictionary = windows[wi]
		if not _window_accepts_threat(window, threat):
			last_skip = "timing_mismatch"
			continue
		var probe := _probe_at_window(live_gs, seat, moves, windows, wi, window, threat, scorer, with_recapture)
		if probe.is_empty() or (probe.has("skip_reason") and not probe.has("window_delta")):
			last_skip = str(probe.get("skip_reason", "probe_failed"))
			continue
		var d := float(probe.get("window_delta", 0.0))
		if d > best_delta:
			best_delta = d
			best = probe
	if best.is_empty():
		return {
			"card_id": str(threat.get("card_id", "")),
			"p_in_hand": float(threat.get("p_in_hand", 0.0)),
			"window_delta": 0.0,
			"broken_claims": [],
			"script_legal": true,
			"plan_broken": false,
			"assumed_card": str(threat.get("card_id", "")),
			"can_recapture": false,
			"note": "threat_not_legal_in_any_window",
			"skip_reason": last_skip if last_skip != "" else "not_legal_in_any_window",
		}
	best["p_in_hand"] = float(threat.get("p_in_hand", 0.0))
	return best


func _probe_at_window(
	live_gs: GameState,
	seat: int,
	moves: Array,
	windows: Array,
	window_index: int,
	window: Dictionary,
	threat: Dictionary,
	scorer: RefCounted,
	with_recapture: bool,
) -> Dictionary:
	var prefix: Array = _prefix_for_window(moves, windows, window_index)
	if prefix.is_empty():
		return {"skip_reason": "empty_prefix"}
	var replay = LineReplayerScript.new().replay_line(live_gs, prefix, seat, {"stop_at_opponent": true})
	if not bool(replay.get("ok", false)):
		return {"skip_reason": "replay_failed"}
	var boundary_gs: GameState = replay.get("gs")
	if boundary_gs == null:
		return {"skip_reason": "replay_failed"}
	var boundary: Dictionary = replay.get("boundary", {})
	var acting := int(boundary.get("acting_seat", -1))
	if acting < 0 or acting == seat:
		return {"skip_reason": "not_opponent_window"}

	var pre_snap := ScoreModelScript.snapshot(boundary_gs, seat)
	var remaining: Array = replay.get("remaining", [])

	var pass_data := _resolve_opponent_pass(boundary_gs, seat)
	if pass_data.get("gs", null) == null:
		return {"skip_reason": "pass_resolve_failed"}
	var threat_snap_data := _resolve_threat_response(
		boundary_gs, seat, acting, threat, scorer, pre_snap, remaining
	)
	if threat_snap_data.get("gs", null) == null:
		return {"skip_reason": str(threat_snap_data.get("skip_reason", "no_legal_command"))}

	var pass_final := _replay_suffix_and_snapshot(pass_data.get("gs"), remaining, seat)
	var threat_final := _replay_suffix_and_snapshot(threat_snap_data.get("gs"), remaining, seat)
	var pass_snap: Dictionary = pass_final.get("snapshot", {})
	var threat_snap: Dictionary = threat_final.get("snapshot", {})

	var pass_score := _score_snapshot(pre_snap, pass_snap, scorer, seat)
	var threat_score := _score_snapshot(pre_snap, threat_snap, scorer, seat)
	var pass_delta := MoveSimulatorScript.new().build_delta(pre_snap, pass_snap, _null_gs_from_snapshot(boundary_gs, pass_snap))
	var threat_delta := MoveSimulatorScript.new().build_delta(pre_snap, threat_snap, _null_gs_from_snapshot(boundary_gs, threat_snap))
	var broken := _broken_claims(pass_delta, threat_delta)

	var script_legal := bool(threat_final.get("ok", false))
	var plan_broken := not script_legal
	var score_after_recapture = null
	var gs_after_threat: GameState = threat_final.get("gs")
	if with_recapture and gs_after_threat != null:
		var rec = _search_recapture(gs_after_threat, seat)
		if not rec.is_empty():
			score_after_recapture = rec.get("score_after_recapture")

	return {
		"card_id": str(threat.get("card_id", "")),
		"assumed_card": str(threat.get("card_id", "")),
		"window_after_move": str(window.get("after_move", "")),
		"window_delta": pass_score - threat_score,
		"broken_claims": broken,
		"script_legal": script_legal,
		"plan_broken": plan_broken,
		"can_recapture": _can_recapture_at_window(boundary_gs, seat),
		"score_after_recapture": score_after_recapture,
	}


func _search_recapture(gs: GameState, seat: int) -> Dictionary:
	var mode := "reactive" if gs.is_closed_chain_state() or gs.current_state == TurnStateMachine.State.SHOWDOWN_OPEN else "main"
	var searcher = TurnSearchScript.new()
	var result: Dictionary = searcher.search(gs, seat, {
		"mode": mode,
		"top_n": 1,
		"node_budget": 40,
		"time_budget_ms": 100,
		"max_depth": 4,
	})
	var lines: Array = result.get("candidate_lines", [])
	if lines.is_empty():
		return {}
	return {
		"score_after_recapture": float((lines[0] as Dictionary).get("score", 0.0)),
		"moves": (lines[0] as Dictionary).get("moves", []),
	}


func _replay_suffix_and_snapshot(gs: GameState, remaining: Array, seat: int) -> Dictionary:
	if gs == null:
		return {"ok": false, "snapshot": {}, "gs": null}
	if remaining.is_empty():
		return {"ok": true, "snapshot": ScoreModelScript.snapshot(gs, seat), "gs": gs}
	var replay_rest = LineReplayerScript.new().replay_line(gs, remaining, seat, {"stop_at_opponent": false})
	var rest_gs: GameState = replay_rest.get("gs")
	var ok := bool(replay_rest.get("ok", false)) and (replay_rest.get("remaining", []) as Array).is_empty()
	var snap_gs: GameState = rest_gs if rest_gs != null else gs
	return {"ok": ok, "snapshot": ScoreModelScript.snapshot(snap_gs, seat), "gs": snap_gs}


func _resolve_opponent_pass(gs: GameState, seat: int) -> Dictionary:
	var sim = MoveSimulatorScript.new()
	var sc: GameController = sim.build_sim_controller(gs)
	if sc == null:
		return {}
	sim.ai_index = seat
	var acting := int(gs.priority_player_index if gs.is_closed_chain_state() else gs.focus_player_index)
	if acting >= 0:
		sc.submit_command(acting, "pass")
		sim.advance_opponent_windows(sc, "pass", [])
	var snap := ScoreModelScript.snapshot(sc.gs, seat)
	var result_gs: GameState = sc.gs.clone()
	sc.free()
	return {"snapshot": snap, "gs": result_gs}


func _resolve_threat_response(
	gs: GameState,
	seat: int,
	acting: int,
	threat: Dictionary,
	scorer: RefCounted,
	pre_snap: Dictionary,
	remaining: Array,
) -> Dictionary:
	var threat_id := str(threat.get("card_id", ""))
	var tmp_sim := MoveSimulatorScript.new()
	var root_sc: GameController = tmp_sim.build_sim_controller(gs)
	if root_sc == null:
		return {"skip_reason": "clone_failed"}
	var injected := _inject_assumed_threat(root_sc.gs, acting, threat_id)
	if injected == "":
		root_sc.free()
		return {"skip_reason": "inject_failed"}
	var legal: Array = LegalMoveEnumeratorScript.enumerate(root_sc.gs, acting)
	var candidate_cmds: Array = []
	for cmd in legal:
		var s := str(cmd)
		if s.begins_with("react %s" % injected) or s.begins_with("play %s" % injected):
			candidate_cmds.append(s)
	if candidate_cmds.is_empty():
		root_sc.free()
		return {"skip_reason": "no_legal_command"}
	var best_score := INF
	var best_gs: GameState = null
	for cmd in candidate_cmds:
		var sc: GameController = tmp_sim.build_sim_controller(root_sc.gs)
		if sc == null:
			continue
		tmp_sim.ai_index = seat
		sc.submit_command(acting, str(cmd))
		if sc.last_command_error:
			sc.free()
			continue
		tmp_sim.advance_to_quiescence(sc, str(cmd), [])
		var after_quiescence: GameState = sc.gs.clone()
		sc.free()
		var final := _replay_suffix_and_snapshot(after_quiescence, remaining, seat)
		var snap: Dictionary = final.get("snapshot", {})
		var score := float(_score_snapshot(pre_snap, snap, scorer, seat))
		if score < best_score:
			best_score = score
			best_gs = after_quiescence
	root_sc.free()
	if best_gs == null:
		return {"skip_reason": "command_rejected"}
	return {"gs": best_gs}


func _inject_assumed_threat(gs: GameState, opponent_seat: int, card_id: String) -> String:
	if card_id == "":
		return ""
	var def := CardLoaderScript.get_card(card_id)
	if def == null:
		return ""
	var opp: PlayerState = gs.players[opponent_seat]
	var inst: CardInstance = opp.create_instance(def)
	inst.location = "hand"
	opp.hand.clear()
	opp.hand.append(inst)
	return inst.instance_id


func _can_recapture_at_window(gs: GameState, seat: int) -> bool:
	var legal: Array = LegalMoveEnumeratorScript.enumerate(gs, seat)
	for cmd in legal:
		var s := str(cmd)
		if s.begins_with("react ") or s.begins_with("play "):
			return true
	return false


func _score_snapshot(root_snap: Dictionary, snap: Dictionary, scorer: RefCounted, seat: int) -> float:
	var feats := ScoreModelScript.build_score_features(root_snap, snap, [])
	feats["ai_index"] = seat
	var scored: Dictionary = scorer.score_with_breakdown(feats)
	return float(scored.get("score", 0.0))


func _window_accepts_threat(window: Dictionary, threat: Dictionary) -> bool:
	var classes: Array = window.get("legal_response_classes", [])
	var timing: String = str(threat.get("timing", "reaction"))
	for c in classes:
		var cs := str(c).to_lower()
		if timing == "reaction" and cs == "reaction":
			return true
		if timing == "action_or_reaction" and (cs == "reaction" or cs == "action"):
			return true
	return false


func _broken_claims(pass_delta: Dictionary, threat_delta: Dictionary) -> Array:
	var out: Array = []
	if bool(pass_delta.get("conquer", false)) and not bool(threat_delta.get("conquer", false)):
		out.append("conquer")
	if int(pass_delta.get("my_score_after", 0)) != int(threat_delta.get("my_score_after", 0)):
		out.append("my_score_after")
	if int(pass_delta.get("opp_score_after", 0)) != int(threat_delta.get("opp_score_after", 0)):
		out.append("opp_score_after")
	var p_ctrl: Dictionary = pass_delta.get("controllers_after", {})
	var t_ctrl: Dictionary = threat_delta.get("controllers_after", {})
	for k in p_ctrl.keys():
		if str(p_ctrl.get(k, "")) != str(t_ctrl.get(k, "")):
			out.append("controller:%s" % str(k))
	return out


func _build_threat_catalog(
	live_gs: GameState,
	seat: int,
	windows: Array,
	prior_data: Dictionary,
) -> Array:
	var out: Array = []
	var opp_seat := 1 - seat
	var opp: PlayerState = live_gs.players[opp_seat]
	var hand_n := opp.hand.size()
	var legend_id := ""
	if opp.legend != null and opp.legend.definition != null:
		legend_id = str(opp.legend.definition.id)
	var priors: Array = []
	if prior_data.has(legend_id):
		priors = prior_data.get(legend_id, [])
	elif prior_data.has("generic_reactions"):
		priors = prior_data.get("generic_reactions", [])
	var known = _seen_counts(live_gs, opp_seat)
	for entry in priors:
		if not (entry is Dictionary):
			continue
		var card_id := str(entry.get("card_id", ""))
		if card_id == "":
			continue
		var def := CardLoaderScript.get_card(card_id)
		if def == null:
			continue
		if not bool(def.is_action) and not bool(def.is_reaction):
			continue
		var timing := "action_or_reaction" if bool(def.is_action) else "reaction"
		var copies := float(entry.get("avg_copies", 1.0))
		var remain := maxf(0.0, copies - float(known.get(card_id, 0)))
		if remain <= 0.0:
			continue
		var play_rate := float(entry.get("play_rate", 0.05))
		var p := play_rate * _p_at_least_one(40, remain, hand_n)
		out.append({
			"card_id": card_id,
			"timing": timing,
			"p_in_hand": p,
		})
	return out


func _seen_counts(gs: GameState, opp_seat: int) -> Dictionary:
	var counts: Dictionary = {}
	var opp: PlayerState = gs.players[opp_seat]
	for c in opp.trash:
		var cid := str(c.definition.id)
		counts[cid] = int(counts.get(cid, 0)) + 1
	for c in opp.base_permanents:
		var cid := str(c.definition.id)
		counts[cid] = int(counts.get(cid, 0)) + 1
	for c in gs.all_units_on_board():
		if c.owner_index != opp_seat:
			continue
		var cid := str(c.definition.id)
		counts[cid] = int(counts.get(cid, 0)) + 1
	return counts


func _p_at_least_one(deck_size: int, copies: float, hand_n: int) -> float:
	if deck_size <= 0 or copies <= 0.0 or hand_n <= 0:
		return 0.0
	var miss := 1.0
	for i in range(hand_n):
		var num := maxf(float(deck_size) - copies - float(i), 0.0)
		var den := maxf(float(deck_size) - float(i), 1.0)
		miss *= num / den
	return 1.0 - miss


func _prefix_for_window(moves: Array, windows: Array, window_index: int) -> Array:
	var target_after := ""
	var target_occ := 0
	if window_index >= 0 and window_index < windows.size():
		target_after = str((windows[window_index] as Dictionary).get("after_move", ""))
		for i in range(window_index + 1):
			if str((windows[i] as Dictionary).get("after_move", "")) == target_after:
				target_occ += 1
	var keep := moves.size()
	if target_after != "":
		var seen := 0
		for i in range(moves.size()):
			if str(moves[i]) == target_after:
				seen += 1
				if seen >= target_occ:
					keep = i + 1
					break
	else:
		keep = mini(moves.size(), window_index + 1)
	var out: Array = []
	for i in range(keep):
		out.append(str(moves[i]))
	return out


func _null_gs_from_snapshot(base_gs: GameState, _snap: Dictionary) -> GameState:
	return base_gs
