class_name SelfPlayCaptureLog
extends RefCounted

# Process-wide JSONL capture sink for offline self-play.
#
# In offline self-play mode (RIFTBOUND_SELFPLAY_CAPTURE) the engine does NOT call
# the Python agent server. Instead every payload that would have been POSTed is
# appended here as one JSON object per line, in emission order. After the run,
# ai_agent/import_selfplay_logs.py replays the file into SQLite using the exact
# same capture code the live server uses.
#
# Both AIPlayer seats share one file (static handle) so records interleave in the
# true order the games produced them — which the importer relies on (the
# decision_index counter and outcome/decision pairing are order-sensitive).

const DEFAULT_PATH := "res://out/selfplay_capture.jsonl"

static var _file: FileAccess = null
static var _path: String = ""
static var _count: int = 0


# Open (truncating) the capture file once per process. Safe to call from each
# seat's setup(); the first call opens it, later calls are no-ops.
static func open_log(path: String = "") -> bool:
	if _file != null:
		return true
	var target := path if path != "" else DEFAULT_PATH
	# Ensure the parent directory exists (res://out is the conventional sink).
	var dir_path := target.get_base_dir()
	if dir_path != "":
		DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(dir_path) if dir_path.begins_with("res://") else dir_path)
	_file = FileAccess.open(target, FileAccess.WRITE)
	if _file == null:
		push_error("SelfPlayCaptureLog: could not open %s (err=%d)" % [target, FileAccess.get_open_error()])
		return false
	_path = target
	_count = 0
	return true


static func is_open() -> bool:
	return _file != null


static func path() -> String:
	return _path


static func count() -> int:
	return _count


# Append one record. `kind` is stamped into the object so the importer can
# dispatch. The body dict is merged in (its keys must not collide with "kind").
static func append(kind: String, body: Dictionary) -> void:
	if _file == null:
		return
	var rec := body.duplicate(true)
	rec["kind"] = kind
	_file.store_line(JSON.stringify(rec))
	_count += 1


static func flush() -> void:
	if _file != null:
		_file.flush()


static func close_log() -> void:
	if _file != null:
		_file.flush()
		_file.close()
		_file = null
