class_name RiskScore
extends RefCounted

## Mirrors ai_agent/risk_score.py for offline / capture argmax parity.
## Risk numbers are signed score impact (≤ 0 when an interrupt hurts).
## recapture_gap / pessimistic_worst are belief-weighted by p_in_hand.
## score_after_recapture must use the same decision-time root as line.score
## (see LineRiskProbe._search_recapture); do not compare post-threat search scores.


static func compute_adjustment(line: Dictionary) -> Dictionary:
	var score := float(line.get("score", 0.0))
	var risk: Dictionary = line.get("risk", {}) if line.get("risk", null) is Dictionary else {}
	var risk_worst := float(risk.get("risk_worst", 0.0))
	var risk_expected := float(risk.get("risk_expected", 0.0))
	var threats: Array = risk.get("threats", []) if risk.get("threats", null) is Array else []
	var needs_recapture := bool(risk.get("needs_recapture", false))
	var plan_broken := false
	var best_delta := INF
	var recapture = null
	var belief_p := 1.0
	for t in threats:
		if not (t is Dictionary):
			continue
		if bool(t.get("plan_broken", false)):
			plan_broken = true
		var d := float(t.get("window_delta", 0.0))
		if d < best_delta:
			best_delta = d
			belief_p = 1.0
			if t.has("p_in_hand"):
				var raw_p = t.get("p_in_hand")
				if typeof(raw_p) == TYPE_FLOAT or typeof(raw_p) == TYPE_INT:
					belief_p = clampf(float(raw_p), 0.0, 1.0)
			var raw = t.get("score_after_recapture", null)
			if typeof(raw) == TYPE_FLOAT or typeof(raw) == TYPE_INT:
				recapture = float(raw)
			else:
				recapture = null
	var penalty := 0.0
	var method := "expected"
	if recapture != null:
		penalty = belief_p * minf(0.0, float(recapture) - score)
		method = "recapture_gap"
	elif needs_recapture or plan_broken:
		penalty = belief_p * risk_worst
		method = "pessimistic_worst"
	else:
		penalty = risk_expected
		method = "expected"
	return {
		"risk_penalty": snapped(penalty, 0.001),
		"risk_adjusted_score": snapped(score + penalty, 0.001),
		"risk_adjustment_method": method,
	}


static func apply_to_line(line: Dictionary) -> Dictionary:
	var out: Dictionary = line.duplicate(true)
	var adj := compute_adjustment(out)
	out["risk_penalty"] = adj["risk_penalty"]
	out["risk_adjusted_score"] = adj["risk_adjusted_score"]
	out["risk_adjustment_method"] = adj["risk_adjustment_method"]
	out["risk_expanded"] = bool(out.get("risk_expanded", false))
	return out


static func annotate_lines(lines: Array) -> Array:
	var out: Array = []
	for line in lines:
		if line is Dictionary:
			out.append(apply_to_line(line))
		else:
			out.append(line)
	out.sort_custom(func(a, b):
		return float(a.get("risk_adjusted_score", a.get("score", 0.0))) > \
			float(b.get("risk_adjusted_score", b.get("score", 0.0)))
	)
	return out


static func rank_score(line: Dictionary) -> float:
	if line.has("risk_adjusted_score") and line.get("risk_adjusted_score", null) != null:
		return float(line.get("risk_adjusted_score", 0.0))
	return float(line.get("score", 0.0))
