class_name EngineServer
extends Node

# Phase 2 — Live Godot engine HTTP server (Deliberative Reasoning Toolkit).
#
# Python tools call back into the rules engine mid-reasoning while AIPlayer awaits
# /goals or /decision. The main loop only pumps TCPServer accept/read/write;
# MoveSimulator / TurnSearch run on a worker Thread against a clone of the
# per-decision pinned GameState.
#
# Endpoints:
#   GET  /engine/health
#   POST /engine/simulate  {moves: [...], seat?: int}
#   POST /engine/search    {budget?, top_n?, mode?, seed_moves?, ...}

const MoveSimulatorScript = preload("res://Scripts/Game/MoveSimulator.gd")
const TurnSearchScript = preload("res://Scripts/Game/TurnSearch.gd")

const DEFAULT_PORT := 8766
const MAX_QUEUE := 8
const READ_CHUNK := 65536

var _server: TCPServer = null
var _port: int = DEFAULT_PORT
var _pinned: GameState = null
var _seat: int = 0
var _profile_path: String = ""

# Peers with an in-progress HTTP request (headers/body not complete yet).
var _reading: Array = []  # Array of {peer, buf}
# Jobs waiting for the worker (serialized — one in-flight heavy job).
var _queue: Array = []  # Array of {peer, method, path, body}
var _busy: bool = false
var _worker: Thread = null
var _worker_peer: StreamPeerTCP = null
var _worker_result: Dictionary = {}


func start(port: int = -1, profile_path: String = "") -> Error:
	if _server != null:
		return OK
	_profile_path = profile_path
	# port < 0 → default 8766; port == 0 → OS-assigned ephemeral.
	if port < 0:
		_port = DEFAULT_PORT
	else:
		_port = port
	_server = TCPServer.new()
	var err := _server.listen(_port, "127.0.0.1")
	if err != OK:
		push_warning("EngineServer: listen failed on 127.0.0.1:%d (err=%d)" % [_port, err])
		_server = null
		return err
	_port = _server.get_local_port()
	set_process(true)
	print("EngineServer: listening on 127.0.0.1:%d" % _port)
	return OK


func stop() -> void:
	set_process(false)
	_drain_worker()
	for item in _reading:
		var peer: StreamPeerTCP = item.get("peer")
		if peer != null:
			peer.disconnect_from_host()
	_reading.clear()
	for job in _queue:
		var peer: StreamPeerTCP = job.get("peer")
		if peer != null:
			_write_json(peer, 503, {"error": "engine server stopping"})
			peer.disconnect_from_host()
	_queue.clear()
	if _server != null:
		_server.stop()
		_server = null
	clear_pin()


func get_port() -> int:
	return _port


func is_pinned() -> bool:
	return _pinned != null


func pin_state(gs: GameState, seat: int) -> void:
	if gs == null:
		clear_pin()
		return
	_pinned = gs.clone()
	_seat = seat


func clear_pin() -> void:
	_pinned = null


func _process(_delta: float) -> void:
	if _server == null:
		return
	_accept_peers()
	_poll_readers()
	_poll_worker()
	_kick_queue()


func _accept_peers() -> void:
	while _server.is_connection_available():
		var peer := _server.take_connection()
		if peer == null:
			break
		_reading.append({"peer": peer, "buf": PackedByteArray()})


func _poll_readers() -> void:
	var still: Array = []
	for item in _reading:
		var peer: StreamPeerTCP = item["peer"]
		peer.poll()
		var status := peer.get_status()
		if status != StreamPeerTCP.STATUS_CONNECTED:
			continue
		var available := peer.get_available_bytes()
		if available > 0:
			var got: Array = peer.get_partial_data(mini(available, READ_CHUNK))
			if int(got[0]) == OK:
				item["buf"].append_array(got[1])
		var parsed := _try_parse_http(item["buf"])
		if parsed.is_empty():
			still.append(item)
			continue
		_dispatch(peer, str(parsed.get("method", "")), str(parsed.get("path", "")), parsed.get("body", {}))
	_reading = still


func _try_parse_http(buf: PackedByteArray) -> Dictionary:
	if buf.is_empty():
		return {}
	var text := buf.get_string_from_utf8()
	var sep := text.find("\r\n\r\n")
	if sep < 0:
		return {}
	var header_text := text.substr(0, sep)
	var lines := header_text.split("\r\n")
	if lines.is_empty():
		return {}
	var request_line := lines[0].split(" ")
	if request_line.size() < 2:
		return {}
	var method := request_line[0].to_upper()
	var path := request_line[1]
	var content_length := 0
	for i in range(1, lines.size()):
		var lower := lines[i].to_lower()
		if lower.begins_with("content-length:"):
			content_length = int(lower.substr("content-length:".length()).strip_edges())
	var body_start := sep + 4
	var body_bytes := buf.slice(body_start)
	if body_bytes.size() < content_length:
		return {}
	var body: Variant = {}
	if content_length > 0:
		var body_text := body_bytes.slice(0, content_length).get_string_from_utf8()
		var parsed = JSON.parse_string(body_text)
		if parsed == null:
			body = {}
		else:
			body = parsed
	return {"method": method, "path": path, "body": body}


func _dispatch(peer: StreamPeerTCP, method: String, path: String, body: Variant) -> void:
	var path_only := path.split("?")[0]
	if method == "GET" and path_only == "/engine/health":
		_write_json(peer, 200, {
			"ok": true,
			"pinned": _pinned != null,
			"port": _port,
			"busy": _busy,
			"queue_depth": _queue.size(),
		})
		peer.disconnect_from_host()
		return
	if method == "POST" and path_only in ["/engine/simulate", "/engine/search"]:
		if _pinned == null:
			_write_json(peer, 409, {"error": "no game state pinned for this decision"})
			peer.disconnect_from_host()
			return
		if _queue.size() >= MAX_QUEUE:
			_write_json(peer, 503, {"error": "engine queue full"})
			peer.disconnect_from_host()
			return
		var body_dict: Dictionary = body if body is Dictionary else {}
		_queue.append({
			"peer": peer,
			"method": method,
			"path": path_only,
			"body": body_dict,
		})
		return
	_write_json(peer, 404, {"error": "unknown path", "path": path_only})
	peer.disconnect_from_host()


func _kick_queue() -> void:
	if _busy or _queue.is_empty() or _pinned == null:
		return
	var job: Dictionary = _queue.pop_front()
	var peer: StreamPeerTCP = job["peer"]
	var path: String = str(job.get("path", ""))
	var body: Dictionary = job.get("body", {})
	var work_gs: GameState = _pinned.clone()
	if work_gs == null:
		_write_json(peer, 500, {"error": "failed to clone pinned state"})
		peer.disconnect_from_host()
		return
	var seat := int(body.get("seat", _seat))
	_busy = true
	_worker_peer = peer
	_worker_result = {}
	_worker = Thread.new()
	var kind := "simulate" if path.ends_with("/simulate") else "search"
	var start_err := _worker.start(_worker_entry.bind(kind, body, work_gs, seat, _profile_path))
	if start_err != OK:
		_busy = false
		_worker = null
		_worker_peer = null
		_write_json(peer, 500, {"error": "failed to start worker thread", "err": start_err})
		peer.disconnect_from_host()


func _worker_entry(kind: String, body: Dictionary, gs: GameState, seat: int, profile_path: String) -> void:
	# Runs off the main thread. Operates only on the cloned GameState; never
	# touches the scene tree.
	if kind == "simulate":
		var moves: Array = body.get("moves", [])
		var cmds: Array = []
		for m in moves:
			cmds.append(str(m))
		var sim = MoveSimulatorScript.new()
		_worker_result = sim.simulate_line(gs, seat, cmds)
		return
	# search
	var options := {
		"mode": str(body.get("mode", "main")),
		"top_n": int(body.get("top_n", 5)),
	}
	var budget: Dictionary = body.get("budget", {}) if body.get("budget", null) is Dictionary else {}
	if budget.has("node_budget"):
		options["node_budget"] = int(budget["node_budget"])
	elif body.has("node_budget"):
		options["node_budget"] = int(body["node_budget"])
	if budget.has("time_budget_ms"):
		options["time_budget_ms"] = int(budget["time_budget_ms"])
	elif body.has("time_budget_ms"):
		options["time_budget_ms"] = int(body["time_budget_ms"])
	if budget.has("max_depth"):
		options["max_depth"] = int(budget["max_depth"])
	elif body.has("max_depth"):
		options["max_depth"] = int(body["max_depth"])
	if budget.has("beam_width"):
		options["beam_width"] = int(budget["beam_width"])
	elif body.has("beam_width"):
		options["beam_width"] = int(body["beam_width"])
	if body.has("seed_moves"):
		options["seed_moves"] = body["seed_moves"]
	var overlay: Dictionary = {}
	if body.get("overlay", null) is Dictionary:
		overlay = body["overlay"]
	var search_profile := profile_path
	if str(body.get("profile_path", "")) != "":
		search_profile = str(body["profile_path"])
	var searcher = TurnSearchScript.new(search_profile, overlay)
	_worker_result = searcher.search(gs, seat, options)


func _poll_worker() -> void:
	if not _busy or _worker == null:
		return
	if _worker.is_alive():
		return
	_worker.wait_to_finish()
	var peer := _worker_peer
	var result := _worker_result.duplicate(true)
	_worker = null
	_worker_peer = null
	_worker_result = {}
	_busy = false
	if peer == null:
		return
	peer.poll()
	if peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		return
	_write_json(peer, 200, result)
	peer.disconnect_from_host()


func _drain_worker() -> void:
	if _worker == null:
		return
	if _worker.is_alive():
		_worker.wait_to_finish()
	_worker = null
	_busy = false
	if _worker_peer != null:
		_worker_peer.disconnect_from_host()
		_worker_peer = null
	_worker_result = {}


func _write_json(peer: StreamPeerTCP, code: int, payload: Dictionary) -> void:
	var body := JSON.stringify(payload)
	var body_bytes := body.to_utf8_buffer()
	var reason := "OK" if code == 200 else "Error"
	if code == 404:
		reason = "Not Found"
	elif code == 409:
		reason = "Conflict"
	elif code == 500:
		reason = "Internal Server Error"
	elif code == 503:
		reason = "Service Unavailable"
	var header := (
		"HTTP/1.1 %d %s\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n"
		% [code, reason, body_bytes.size()]
	)
	peer.put_data(header.to_utf8_buffer())
	peer.put_data(body_bytes)
