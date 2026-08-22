from __future__ import annotations

from ai_agent import schemas, skills


def test_candidate_line_accepts_risk_payload():
    line = schemas.CandidateLine.model_validate(
        {
            "line_id": "line-1",
            "moves": ["pass"],
            "score": 1.0,
            "risk": {
                "risk_worst": 2.5,
                "risk_expected": 1.1,
                "threats": [{"card_id": "defy", "window_delta": 2.5}],
            },
        }
    )
    assert line.risk["risk_worst"] == 2.5


def test_expand_risk_requires_line_id_or_moves():
    out = skills.expand_risk()
    assert out["ok"] is False
    assert "needs a known line_id" in out["error"]
