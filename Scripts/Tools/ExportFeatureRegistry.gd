extends SceneTree

# Headless exporter for the feature-registry manifest.
#
# Writes Data/AI/feature_registry.json from FeatureRegistry.specs() (the GDScript
# single source of truth) plus the situational specs in
# Data/AI/situational_features.json. The Python tuning/reporting tools
# (texel_tune.py, feature_report.py) load that manifest so they can never drift
# from the GDScript scorer. Re-run this whenever you add/edit a feature spec:
#
#   <godot> --headless --script res://Scripts/Tools/ExportFeatureRegistry.gd
#
# Optional: -- --out res://path/to/manifest.json

const FeatureRegistryScript = preload("res://Scripts/Game/FeatureRegistry.gd")

const DEFAULT_OUT := "res://Data/AI/feature_registry.json"
const SITUATIONAL_PATH := "res://Data/AI/situational_features.json"


func _initialize() -> void:
	var out_path := DEFAULT_OUT
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--out" and i + 1 < args.size():
			out_path = args[i + 1]

	var situational := _load_situational()
	var manifest := FeatureRegistryScript.export_manifest(situational)

	var file := FileAccess.open(out_path, FileAccess.WRITE)
	if file == null:
		push_error("ExportFeatureRegistry: cannot write %s" % out_path)
		quit(1)
		return
	file.store_string(JSON.stringify(manifest, "  "))
	file.close()
	print("Wrote feature manifest: %s (%d core specs, %d situational)" % [
		out_path, manifest["specs"].size(), situational.size(),
	])
	quit(0)


func _load_situational() -> Array:
	var file := FileAccess.open(SITUATIONAL_PATH, FileAccess.READ)
	if file == null:
		return []
	var parsed = JSON.parse_string(file.get_as_text())
	if parsed is Dictionary:
		return parsed.get("features", [])
	return []
