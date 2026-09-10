"""Commit-gate tests for risk_adjusted_score rationale requirement."""
from __future__ import annotations

from types import SimpleNamespace

from ai_agent.reasoner import _risk_commit_rationale_error


def _ctx(scout_lines):
    return SimpleNamespace(scout_lines=scout_lines)


def test_commit_ok_when_near_leader(monkeypatch):
    monkeypatch.setenv("RIFTBOUND_LINE_RISK", "1")
    monkeypatch.setenv("RIFTBOUND_RISK_RANK", "1")
    scout = [
        {"line_id": "leader", "complete": True, "risk_adjusted_score": 5.0},
        {"line_id": "alt", "complete": True, "risk_adjusted_score": 4.6},
    ]
    err = _risk_commit_rationale_error(
        scout[1],
        "Prefer alt for board presence.",
        _ctx(scout),
    )
    assert err is None


def test_commit_rejected_without_risk_rationale(monkeypatch):
    monkeypatch.setenv("RIFTBOUND_LINE_RISK", "1")
    monkeypatch.setenv("RIFTBOUND_RISK_RANK", "1")
    scout = [
        {"line_id": "leader", "complete": True, "risk_adjusted_score": 5.0},
    ]
    chosen = {
        "line_id": "risky",
        "complete": True,
        "risk_adjusted_score": 2.0,
        "risk": {"threats": [{"card_id": "defy"}]},
    }
    err = _risk_commit_rationale_error(
        chosen,
        "Prefer this for more might on the battlefield.",
        _ctx(scout),
    )
    assert err is not None
    assert "risk_adjusted_score" in err


def test_commit_accepted_with_risk_rationale(monkeypatch):
    monkeypatch.setenv("RIFTBOUND_LINE_RISK", "1")
    monkeypatch.setenv("RIFTBOUND_RISK_RANK", "1")
    scout = [
        {"line_id": "leader", "complete": True, "risk_adjusted_score": 5.0},
    ]
    chosen = {
        "line_id": "safer",
        "complete": True,
        "risk_adjusted_score": 2.0,
        "risk": {"threats": [{"card_id": "defy"}]},
    }
    err = _risk_commit_rationale_error(
        chosen,
        "Accept lower risk_adjusted_score because defy interrupt is unlikely and recapture holds.",
        _ctx(scout),
    )
    assert err is None


def test_commit_accepted_mentioning_threat_card(monkeypatch):
    monkeypatch.setenv("RIFTBOUND_LINE_RISK", "1")
    monkeypatch.setenv("RIFTBOUND_RISK_RANK", "1")
    scout = [
        {"line_id": "leader", "complete": True, "risk_adjusted_score": 5.0},
    ]
    chosen = {
        "line_id": "safer",
        "complete": True,
        "risk_adjusted_score": 1.0,
        "risk": {"threats": [{"card_id": "discipline"}]},
    }
    err = _risk_commit_rationale_error(
        chosen,
        "discipline is not in their open runes so the interrupt is empty.",
        _ctx(scout),
    )
    assert err is None
