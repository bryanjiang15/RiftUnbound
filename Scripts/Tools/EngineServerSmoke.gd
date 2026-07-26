extends SceneTree
#
# Phase 2 headless check for the live EngineServer.
#
# Loads a fixture, pins state, pumps the server, and asserts:
#   GET  /engine/health
#   POST /engine/simulate
#   POST /engine/search
#   POST /engine/search with seed_moves
#
# Run:
#   Godot --headless --path . --script res://Scripts/Tools/EngineServerSmoke.gd

const HarnessScript = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")
const EngineServerScript = preload("res://Scripts/AI/EngineServer.gd")

var _server = null
var _failures: Array = []


func _initialize() -> void:
	print("=== EngineServer Smoke (Godot ", Engine.get_version_info()["string"], ") ===")
	var h = HarnessScript.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/search_winning_line.json")
	var gs: GameState = h.gs()

	_server = EngineServerScript.new()
	# SceneTree scripts have no Node tree by default — attach under root.
	root.add_child(_server)
	if _server.start(0) != OK:
		_fail("listen ephemeral")
		_finish()
		return
	var port: int = int(_server.get_port())
	_server.pin_state(gs, 0)
	# Give the Node one frame to enable _process.
	await process_frame

	_check_health(port)
	_check_simulate(port)
	_check_search(port)
	_check_seeded_search(port)

	_server.stop()
	_finish()


func _finish() -> void:
	if _failures.is_empty():
		print("\n=== ENGINE SERVER SMOKE: PASS ===")
		quit(0)
	else:
		print("\n=== ENGINE SERVER SMOKE: FAIL ===")
		for f in _failures:
			print("  ✗ ", f)
		quit(1)


func _fail(msg: String) -> void:
	_failures.append(msg)
	print("  ✗ ", msg)


func _ok(msg: String) -> void:
	print("  ✓ ", msg)


func _http(port: int, method: String, path: String, body: Dictionary = {}) -> Dictionary:
	var client := StreamPeerTCP.new()
	if client.connect_to_host("127.0.0.1", port) != OK:
		return {"_error": "connect failed"}
	var deadline := Time.get_ticks_msec() + 3000
	while client.get_status() != StreamPeerTCP.STATUS_CONNECTED and Time.get_ticks_msec() < deadline:
		client.poll()
		OS.delay_msec(2)
	if client.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		return {"_error": "connect timeout"}

	var payload := ""
	if method == "POST":
		payload = JSON.stringify(body)
	var req := (
		"%s %s HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s"
		% [method, path, payload.length(), payload]
	)
	client.put_data(req.to_utf8_buffer())

	var buf := PackedByteArray()
	deadline = Time.get_ticks_msec() + 8000
	while Time.get_ticks_msec() < deadline:
		# Pump the engine server while waiting for the worker reply.
		_server._process(0.0)
		client.poll()
		if client.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			break
		var n := client.get_available_bytes()
		if n > 0:
			var got: Array = client.get_partial_data(n)
			if int(got[0]) == OK:
				buf.append_array(got[1])
		if buf.size() > 0 and buf.get_string_from_utf8().find("\r\n\r\n") >= 0:
			# May still be receiving body; keep reading briefly.
			OS.delay_msec(5)
			_server._process(0.0)
			client.poll()
			if client.get_status() == StreamPeerTCP.STATUS_CONNECTED:
				n = client.get_available_bytes()
				if n > 0:
					var got2: Array = client.get_partial_data(n)
					if int(got2[0]) == OK:
						buf.append_array(got2[1])
			# Heuristic: if Content-Length satisfied, stop.
			var partial_text := buf.get_string_from_utf8()
			var partial_sep := partial_text.find("\r\n\r\n")
			if partial_sep >= 0:
				var headers := partial_text.substr(0, partial_sep).to_lower()
				var cl := 0
				for line in headers.split("\r\n"):
					if line.begins_with("content-length:"):
						cl = int(line.substr("content-length:".length()).strip_edges())
				var body_len := buf.size() - (partial_sep + 4)
				if body_len >= cl:
					break
		OS.delay_msec(2)

	client.disconnect_from_host()
	var text := buf.get_string_from_utf8()
	var sep := text.find("\r\n\r\n")
	if sep < 0:
		return {"_error": "no http response", "_raw": text}
	var body_text := text.substr(sep + 4)
	var parsed = JSON.parse_string(body_text)
	if parsed is Dictionary:
		return parsed
	return {"_error": "bad json", "_raw": body_text}


func _check_health(port: int) -> void:
	print("\n[health]")
	var r := _http(port, "GET", "/engine/health")
	if r.get("ok") == true and r.get("pinned") == true:
		_ok("health ok+pinned")
	else:
		_fail("health: %s" % str(r))


func _check_simulate(port: int) -> void:
	print("\n[simulate]")
	# Fixture seat 0 should accept a plain pass in many states; use end turn only
	# if legal. Prefer 'pass' which is almost always accepted in Neutral Open.
	var r := _http(port, "POST", "/engine/simulate", {"moves": ["pass"]})
	if r.has("_error"):
		_fail("simulate transport: %s" % str(r))
		return
	if r.has("resolved_if_unanswered") or r.get("legal") != null:
		_ok("simulate returned legal=%s keys=%s" % [str(r.get("legal")), str(r.keys())])
	else:
		_fail("simulate unexpected: %s" % str(r))


func _check_search(port: int) -> void:
	print("\n[search]")
	var r := _http(port, "POST", "/engine/search", {
		"top_n": 3,
		"budget": {"node_budget": 40, "time_budget_ms": 800, "max_depth": 4, "beam_width": 4},
	})
	if r.has("_error"):
		_fail("search transport: %s" % str(r))
		return
	var lines: Array = r.get("candidate_lines", [])
	if lines.is_empty():
		_fail("search returned no lines: %s" % str(r.get("search_stats", r)))
		return
	var first: Dictionary = lines[0]
	var required := [
		"moves", "move_contexts", "expected_pre_hashes", "search_state",
		"root_state_hash", "legal", "complete", "terminal_reason", "search_mode",
	]
	var has_contract := true
	for key in required:
		if not first.has(key):
			has_contract = false
	var parallel: bool = first.get("moves", []).size() == first.get("move_contexts", []).size() \
		and first.get("moves", []).size() == first.get("expected_pre_hashes", []).size()
	if has_contract and parallel and str(r.get("root_state_hash", "")) == str(first.get("root_state_hash", "")):
		_ok("search %d lines; executable line contract present" % lines.size())
	else:
		_fail("search line missing fields: %s" % str(first.keys()))


func _check_seeded_search(port: int) -> void:
	print("\n[seeded search]")
	# First get a line, then deepen from its prefix.
	var base := _http(port, "POST", "/engine/search", {
		"top_n": 1,
		"budget": {"node_budget": 40, "time_budget_ms": 800, "max_depth": 4, "beam_width": 4},
	})
	var lines: Array = base.get("candidate_lines", [])
	if lines.is_empty():
		_fail("seeded: no base line")
		return
	var moves: Array = lines[0].get("moves", [])
	var seed_moves: Array = []
	for m in moves:
		if str(m) == "end turn":
			break
		seed_moves.append(str(m))
		if seed_moves.size() >= 1:
			break
	if seed_moves.is_empty():
		_ok("seeded skipped (base line had no prefix moves)")
		return
	var r := _http(port, "POST", "/engine/search", {
		"seed_moves": seed_moves,
		"top_n": 3,
		"budget": {"node_budget": 40, "time_budget_ms": 800, "max_depth": 6, "beam_width": 4},
	})
	if r.get("legal") == false:
		_fail("seeded illegal: %s" % str(r.get("error", r)))
		return
	var out_lines: Array = r.get("candidate_lines", [])
	if out_lines.is_empty():
		_fail("seeded returned no lines")
		return
	var first_moves: Array = out_lines[0].get("moves", [])
	if str(r.get("root_state_hash", "")) != str(base.get("root_state_hash", "")):
		_fail("seeded search changed the pinned root identity")
		return
	var prefix_ok := first_moves.size() >= seed_moves.size()
	for i in range(seed_moves.size()):
		if str(first_moves[i]) != str(seed_moves[i]):
			# Intermediate auto-steps may insert between scripted seeds; check
			# that each seed command appears in order.
			prefix_ok = false
			break
	if not prefix_ok:
		# Softer check: every seed command appears in the deepened line.
		var joined := " | ".join(first_moves)
		prefix_ok = true
		for s in seed_moves:
			if joined.find(str(s)) < 0:
				prefix_ok = false
				break
	if prefix_ok:
		_ok("seeded line preserves seed %s" % str(seed_moves))
	else:
		_fail("seeded line missing seed %s in %s" % [str(seed_moves), str(first_moves)])
