from __future__ import annotations

import json

from ai_agent.schemas import Goal, GoalSet
from ai_agent.strategist import _parse_goals


# ── Schema leniency (priority / comparator / kind synonyms) ──────────────────


def test_priority_medium_synonym_accepted():
    g = Goal(id="x", kind="weight_bias", feature="battlefield_control", priority="medium")
    assert g.priority == "med"


def test_priority_unknown_defaults_med():
    g = Goal(id="x", kind="weight_bias", feature="battlefield_control", priority="spicy")
    assert g.priority == "med"


def test_comparator_word_synonyms():
    assert Goal(id="x", kind="state_target", metric="my_score",
                comparator="at_least", threshold=8).comparator == ">="
    assert Goal(id="y", kind="state_target", metric="my_score",
                comparator="atmost", threshold=8).comparator == "<="
    assert Goal(id="z", kind="state_target", metric="my_score",
                comparator="exactly", threshold=8).comparator == "=="


def test_kind_is_lowercased():
    assert Goal(id="x", kind="WEIGHT_BIAS", feature="battlefield_control").kind == "weight_bias"


# ── Lenient parsing (the reported failures) ──────────────────────────────────


def test_parse_drops_one_bad_goal_keeps_good_ones():
    # Mirrors the live log: goal[2] had priority "medium" (now coerced) and one
    # goal references a non-kind — a single bad goal must not nuke the set.
    payload = {
        "schema_version": "1.0", "turn": 5, "rationale": "mix",
        "goals": [
            {"id": "g1", "kind": "weight_bias", "feature": "battlefield_control", "priority": "high"},
            {"id": "g2", "kind": "not_a_real_kind", "priority": "high"},  # invalid → dropped
            {"id": "g3", "kind": "state_target", "metric": "my_ready_runes",
             "comparator": ">=", "threshold": 3, "priority": "medium"},  # coerced med
        ],
    }
    gs = _parse_goals(json.dumps(payload))
    assert gs is not None
    ids = {g.id for g in gs.goals}
    assert ids == {"g1", "g3"}
    assert all(g.priority in ("low", "med", "high") for g in gs.goals)


def test_parse_strips_markdown_fences():
    text = "```json\n{\"turn\": 1, \"goals\": []}\n```"
    gs = _parse_goals(text)
    assert gs is not None and gs.goals == []


def test_parse_extracts_json_from_prose():
    text = 'Here is my plan:\n{"turn": 2, "rationale": "r", "goals": []}\nHope that helps!'
    gs = _parse_goals(text)
    assert gs is not None and gs.turn == 2


def test_parse_empty_content_returns_none():
    assert _parse_goals("") is None
    assert _parse_goals("no json here") is None


def test_parse_caps_goals_at_four():
    payload = {"turn": 1, "goals": [
        {"id": f"g{i}", "kind": "weight_bias", "feature": "battlefield_control"} for i in range(6)
    ]}
    gs = _parse_goals(json.dumps(payload))
    assert gs is not None and len(gs.goals) == 4
