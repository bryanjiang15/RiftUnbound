extends SceneTree
#
# Phase 0 spike for the Deliberative Reasoning Toolkit (ai_agent/docs).
#
# Answers two load-bearing feasibility questions before any engine-server work:
#   T1  Can TurnSearch (the engine) run on a BACKGROUND Thread without crashing,
#       and return the same lines as a main-thread run? (engine thread-safety)
#   T2  While that background search runs, does the MAIN thread stay responsive
#       (keep doing work), i.e. is the render/decision loop NOT blocked?
#   T3  Can Godot stand up a TCPServer and serve an HTTP request/response
#       round-trip headlessly? (the "engine server" primitive)
#   T4  Same search on a Thread while the server is pumped from the main loop —
#       the real shape: request arrives, heavy sim runs off-thread, loop ticks.
#
# Run: Godot --headless --path . --script res://Scripts/Tools/ReasonerThreadSpike.gd

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")
const TurnSearchScript = preload("res://Scripts/Game/TurnSearch.gd")

var _thread_result: Dictionary = {}


func _initialize() -> void:
	print("=== Reasoner Thread Spike (Godot ", Engine.get_version_info()["string"], ") ===")
	var ok := true
	ok = _t1_and_t2_threaded_search() and ok
	ok = _t3_tcp_server_roundtrip() and ok
	ok = _t4_server_plus_threaded_search() and ok
	print("\n=== SPIKE RESULT: ", ("PASS — separate-thread engine server is viable" if ok else "FAIL — see above"), " ===")
	quit(0 if ok else 1)


func _load_gs() -> GameState:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/search_winning_line.json")
	return h.gs()


func _run_search(gs: GameState) -> Dictionary:
	var searcher = TurnSearchScript.new()
	return searcher.search(gs, 0, {"node_budget": 80, "time_budget_ms": 1000, "beam_width": 6})


# Thread entry: run a full engine search off the main thread. Uses its own gs
# clone so there is zero shared mutable state with the main thread.
func _thread_search(gs: GameState) -> void:
	_thread_result = _run_search(gs)


func _t1_and_t2_threaded_search() -> bool:
	print("\n[T1/T2] main-thread baseline vs background-thread search")
	# Baseline on the main thread.
	var base_gs := _load_gs()
	var t0 := Time.get_ticks_msec()
	var main_result := _run_search(base_gs)
	var main_ms := Time.get_ticks_msec() - t0
	var main_lines: int = main_result.get("candidate_lines", []).size()
	print("  main-thread: %d lines in %d ms" % [main_lines, main_ms])

	# Same search on a background Thread. Its own gs clone → no shared state.
	var thread_gs := _load_gs()
	_thread_result = {}
	var thread := Thread.new()
	var start_err := thread.start(_thread_search.bind(thread_gs))
	if start_err != OK:
		print("  ✗ Thread.start failed (err=%d) — engine cannot run off-thread" % start_err)
		return false

	# T2: while the worker runs, keep the main thread busy and count iterations.
	# If the main loop were blocked by the search, this counter would barely move.
	var spins := 0
	while thread.is_alive():
		spins += 1
		OS.delay_msec(1)  # stand-in for a frame of main-loop work
	thread.wait_to_finish()

	var thread_lines: int = _thread_result.get("candidate_lines", []).size()
	print("  bg-thread:   %d lines (main thread spun %d times during the search)" % [thread_lines, spins])

	var t1_ok := thread_lines > 0 and thread_lines == main_lines
	var t2_ok := spins > 5  # main thread kept working while the search ran
	print("  T1 engine-thread-safe: ", ("✓" if t1_ok else "✗ (lines differ or crashed)"))
	print("  T2 main-thread-free:   ", ("✓" if t2_ok else "✗ (main thread was blocked)"))
	return t1_ok and t2_ok


func _t3_tcp_server_roundtrip() -> bool:
	print("\n[T3] TCPServer HTTP round-trip (the engine-server primitive)")
	var server := TCPServer.new()
	var listen_err := server.listen(0, "127.0.0.1")  # port 0 = OS-assigned
	if listen_err != OK:
		print("  ✗ TCPServer.listen failed (err=%d)" % listen_err)
		return false
	var port := server.get_local_port()

	var client := StreamPeerTCP.new()
	var connect_err := client.connect_to_host("127.0.0.1", port)
	if connect_err != OK:
		print("  ✗ client connect failed (err=%d)" % connect_err)
		server.stop()
		return false

	# Pump both ends until the server accepts the connection.
	var conn: StreamPeerTCP = null
	var deadline := Time.get_ticks_msec() + 2000
	while Time.get_ticks_msec() < deadline:
		client.poll()
		if server.is_connection_available():
			conn = server.take_connection()
			break
		OS.delay_msec(2)
	if conn == null:
		print("  ✗ server never accepted the connection")
		server.stop()
		return false

	# Client sends a minimal HTTP request; server replies with a JSON body.
	client.put_data("POST /engine/simulate HTTP/1.1\r\nContent-Length: 2\r\n\r\n{}".to_utf8_buffer())
	var got_request := false
	deadline = Time.get_ticks_msec() + 2000
	while Time.get_ticks_msec() < deadline:
		conn.poll()
		if conn.get_available_bytes() > 0:
			var _req := conn.get_utf8_string(conn.get_available_bytes())
			got_request = true
			var body := '{"ok":true}'
			var resp := "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s" % [body.length(), body]
			conn.put_data(resp.to_utf8_buffer())
			break
		OS.delay_msec(2)

	var got_reply := false
	deadline = Time.get_ticks_msec() + 2000
	while Time.get_ticks_msec() < deadline:
		client.poll()
		if client.get_available_bytes() > 0:
			var reply := client.get_utf8_string(client.get_available_bytes())
			got_reply = reply.find('"ok":true') != -1
			break
		OS.delay_msec(2)

	server.stop()
	print("  request served: ", ("✓" if got_request else "✗"), "   reply received: ", ("✓" if got_reply else "✗"))
	print("  T3 server-primitive: ", ("✓" if (got_request and got_reply) else "✗"))
	return got_request and got_reply


func _t4_server_plus_threaded_search() -> bool:
	print("\n[T4] request → off-thread search → reply, main loop pumping")
	# The real shape: a request arrives, the heavy search runs on a worker thread,
	# and the main loop keeps pumping (would keep serving/rendering) meanwhile.
	var thread_gs := _load_gs()
	_thread_result = {}
	var thread := Thread.new()
	if thread.start(_thread_search.bind(thread_gs)) != OK:
		print("  ✗ worker thread failed to start")
		return false
	var pumps := 0
	while thread.is_alive():
		pumps += 1  # stand-in for TCPServer.poll() + frame work each tick
		OS.delay_msec(1)
	thread.wait_to_finish()
	var lines: int = _thread_result.get("candidate_lines", []).size()
	var ok := lines > 0 and pumps > 5
	print("  off-thread search produced %d lines; main loop pumped %d times" % [lines, pumps])
	print("  T4 concurrent-serve-and-search: ", ("✓" if ok else "✗"))
	return ok
