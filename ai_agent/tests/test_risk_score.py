"""Unit tests for risk-adjusted ranking."""
from __future__ import annotations

import os

from ai_agent.risk_score import (
    apply_risk_adjustment,
    compute_risk_adjustment,
    enrich_lines_with_risk,
    format_pre_llm_banner,
    merge_expanded_risk,
    should_auto_expand,
)


def test_expected_penalty():
    line = {
        "score": 10.0,
        "risk": {"risk_worst": -5.0, "risk_expected": -2.0, "threats": [{"window_delta": -2.0}]},
    }
    adj = compute_risk_adjustment(line)
    assert adj["risk_adjustment_method"] == "expected"
    assert adj["risk_penalty"] == -2.0
    assert adj["risk_adjusted_score"] == 8.0


def test_expected_penalty_lowers_score():
    line = {
        "score": 0.54,
        "risk": {
            "risk_worst": -5.8,
            "risk_expected": -2.02,
            "threats": [{"window_delta": -5.8}],
        },
    }
    adj = compute_risk_adjustment(line)
    assert adj["risk_adjustment_method"] == "expected"
    assert adj["risk_penalty"] == -2.02
    assert adj["risk_adjusted_score"] == -1.48


def test_pessimistic_worst_on_plan_broken():
    line = {
        "score": 10.0,
        "risk": {
            "risk_worst": -7.5,
            "risk_expected": -1.0,
            "needs_recapture": True,
            "threats": [{"window_delta": -7.5, "plan_broken": True}],
        },
    }
    adj = compute_risk_adjustment(line)
    assert adj["risk_adjustment_method"] == "pessimistic_worst"
    assert adj["risk_penalty"] == -7.5
    assert adj["risk_adjusted_score"] == 2.5


def test_recapture_gap():
    """recapture_gap = score_after_recapture - unanswered score.

    Both values must share the decision-time scoring root. LineRiskProbe
    re-scores the recovery leaf against that root; using a post-threat
    TurnSearch score here would be an incompatible baseline.
    """
    line = {
        "score": 10.0,
        "risk": {
            "risk_worst": -8.0,
            "risk_expected": -3.0,
            "threats": [
                {
                    "window_delta": -8.0,
                    "plan_broken": True,
                    "score_after_recapture": 6.0,
                }
            ],
        },
    }
    adj = compute_risk_adjustment(line)
    assert adj["risk_adjustment_method"] == "recapture_gap"
    assert adj["risk_penalty"] == -4.0
    assert adj["risk_adjusted_score"] == 6.0


def test_recapture_gap_weights_by_belief_p():
    line = {
        "score": 8.533,
        "risk": {
            "risk_worst": -12.6,
            "risk_expected": -3.21,
            "threats": [
                {
                    "card_id": "discipline",
                    "p_in_hand": 0.255,
                    "window_delta": -12.6,
                    "plan_broken": True,
                    "score_after_recapture": -3.84,
                }
            ],
        },
    }
    adj = compute_risk_adjustment(line)
    assert adj["risk_adjustment_method"] == "recapture_gap"
    # p * (recapture - score) = 0.255 * -12.373 ≈ -3.155
    assert adj["risk_penalty"] == -3.155
    assert adj["risk_adjusted_score"] == 5.378


def test_pessimistic_worst_weights_by_belief_p():
    line = {
        "score": 10.0,
        "risk": {
            "risk_worst": -8.0,
            "risk_expected": -2.0,
            "needs_recapture": True,
            "threats": [{"window_delta": -8.0, "plan_broken": True, "p_in_hand": 0.25}],
        },
    }
    adj = compute_risk_adjustment(line)
    assert adj["risk_adjustment_method"] == "pessimistic_worst"
    assert adj["risk_penalty"] == -2.0
    assert adj["risk_adjusted_score"] == 8.0


def test_merge_expanded_risk_keeps_cheap_p_and_siblings():
    old = {
        "risk_worst": -12.6,
        "risk_expected": -3.5,
        "threats": [
            {"card_id": "discipline", "p_in_hand": 0.255, "window_delta": -12.6, "plan_broken": True},
            {"card_id": "en-garde", "p_in_hand": 0.166, "window_delta": -0.76},
        ],
    }
    new = {
        "risk_worst": -12.6,
        "risk_expected": -12.6,
        "needs_recapture": True,
        "threats": [
            {
                "card_id": "discipline",
                "p_in_hand": 1.0,
                "window_delta": -12.6,
                "plan_broken": True,
                "score_after_recapture": -3.84,
            }
        ],
    }
    merged = merge_expanded_risk(old, new)
    by_id = {t["card_id"]: t for t in merged["threats"]}
    assert by_id["discipline"]["p_in_hand"] == 0.255
    assert by_id["discipline"]["score_after_recapture"] == -3.84
    assert "en-garde" in by_id
    assert by_id["en-garde"]["p_in_hand"] == 0.166
    assert merged["needs_recapture"] is True
    # expected recomputed with preserved p, not expand's p=1
    assert abs(merged["risk_expected"] - (-12.6 * 0.255 + -0.76 * 0.166)) < 1e-9
    assert merged["risk_worst"] == -12.6


def test_should_auto_expand_threshold(monkeypatch):
    monkeypatch.setenv("RIFTBOUND_LINE_RISK", "1")
    monkeypatch.setenv("RIFTBOUND_RISK_RANK", "1")
    monkeypatch.setenv("RIFTBOUND_RISK_EXPAND_THRESHOLD", "1.0")
    assert should_auto_expand({"risk_worst": -1.5, "threats": []}) is True
    assert should_auto_expand({"risk_worst": -0.2, "threats": []}) is False
    assert should_auto_expand({
        "risk_worst": 0.0,
        "threats": [{"plan_broken": True}],
    }) is True


def test_enrich_sorts_by_risk_adjusted(monkeypatch):
    monkeypatch.setenv("RIFTBOUND_LINE_RISK", "1")
    monkeypatch.setenv("RIFTBOUND_RISK_RANK", "1")
    monkeypatch.setenv("RIFTBOUND_RISK_AUTO_EXPAND", "0")
    lines = [
        {
            "line_id": "a",
            "score": 10.0,
            "risk": {"risk_worst": -9.0, "risk_expected": -9.0, "threats": [{"window_delta": -9.0}]},
        },
        {
            "line_id": "b",
            "score": 8.0,
            "risk": {"risk_worst": 0.0, "risk_expected": 0.0, "threats": []},
        },
    ]
    enriched, telem = enrich_lines_with_risk(lines, auto_expand=False)
    assert enriched[0]["line_id"] == "b"
    assert enriched[0]["risk_adjusted_score"] == 8.0
    assert enriched[1]["line_id"] == "a"
    assert enriched[1]["risk_adjusted_score"] == 1.0
    assert telem["auto_expand_count"] == 0


def test_enrich_auto_expand_merges_risk(monkeypatch):
    monkeypatch.setenv("RIFTBOUND_LINE_RISK", "1")
    monkeypatch.setenv("RIFTBOUND_RISK_RANK", "1")
    monkeypatch.setenv("RIFTBOUND_RISK_AUTO_EXPAND", "1")
    monkeypatch.setenv("RIFTBOUND_RISK_EXPAND_THRESHOLD", "1.0")

    def fake_expand(*, line_id=None, card_id=None, line=None):
        return {
            "ok": True,
            "risk": {
                "risk_worst": -5.0,
                "risk_expected": -5.0,
                "needs_recapture": True,
                "threats": [
                    {
                        "card_id": card_id or "defy",
                        "p_in_hand": 1.0,
                        "window_delta": -5.0,
                        "plan_broken": True,
                        "score_after_recapture": 7.0,
                    }
                ],
            },
        }

    lines = [
        {
            "line_id": "risky",
            "score": 10.0,
            "risk": {
                "risk_worst": -8.0,
                "risk_expected": -2.0,
                "needs_recapture": True,
                "threats": [
                    {
                        "card_id": "defy",
                        "p_in_hand": 0.25,
                        "window_delta": -8.0,
                        "plan_broken": True,
                    }
                ],
            },
        }
    ]
    enriched, telem = enrich_lines_with_risk(
        lines, auto_expand=True, expand_fn=fake_expand
    )
    assert telem["auto_expand_count"] == 1
    assert enriched[0]["risk_expanded"] is True
    assert enriched[0]["risk_adjustment_method"] == "recapture_gap"
    assert enriched[0]["risk"]["threats"][0]["p_in_hand"] == 0.25
    # p * (recapture - score) = 0.25 * (7 - 10) = -0.75 → adj 9.25
    assert enriched[0]["risk_penalty"] == -0.75
    assert enriched[0]["risk_adjusted_score"] == 9.25


def test_format_pre_llm_banner():
    text = format_pre_llm_banner(
        scout_ms=312,
        scout_lines=5,
        cheap_risk_ms=187,
        expand_ms=420,
        expand_count=2,
        total_ms=919,
    )
    assert "scout=312ms lines=5" in text
    assert "cheap_risk=187ms" in text
    assert "expand=420ms n=2" in text
    assert "total=919ms" in text


def test_apply_risk_adjustment_disabled(monkeypatch):
    monkeypatch.setenv("RIFTBOUND_RISK_RANK", "0")
    monkeypatch.setenv("RIFTBOUND_LINE_RISK", "1")
    out = apply_risk_adjustment({"score": 5.0, "risk": {"risk_expected": -3.0}})
    assert out["risk_adjusted_score"] == 5.0
    assert out["risk_adjustment_method"] == "none"
