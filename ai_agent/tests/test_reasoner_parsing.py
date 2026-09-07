from ai_agent.reasoner import _parse_reasoner_emit, _render_scout_lines


def test_parse_direct_line_requires_registry_reference():
    emit = _parse_reasoner_emit(
        'Result:\n```json\n{"kind":"line","confidence":"commit",'
        '"chosen_line_id":"scout-line-1-abc","rationale":"verified"}\n```',
        turn=3,
    )
    assert emit is not None
    assert emit.kind == "line"
    assert emit.chosen_line_id == "scout-line-1-abc"


def test_parse_goal_emit_is_all_or_nothing():
    emit = _parse_reasoner_emit(
        '{"kind":"goals","confidence":"goals","goal_set":{'
        '"turn":3,"rationale":"control",'
        '"goals":['
        '{"id":"ok","kind":"weight_bias","feature":"battlefield_control"},'
        '{"id":"bad","kind":"not-a-kind"}'
        ']}}',
        turn=3,
    )
    assert emit is None


def test_parse_goal_emit_normalizes_current_turn():
    emit = _parse_reasoner_emit(
        '{"kind":"goals","goal_set":{"turn":0,"goals":['
        '{"id":"ok","kind":"weight_bias","feature":"battlefield_control"}'
        ']},"rationale":"control"}',
        turn=7,
    )
    assert emit is not None
    assert emit.goal_set is not None
    assert emit.goal_set.turn == 7


def test_parse_empty_goals_is_invalid():
    assert _parse_reasoner_emit(
        '{"kind":"goals","goal_set":{"goals":[]},"rationale":"noop"}',
        turn=2,
    ) is None


def test_render_scout_lines_includes_risk_summary():
    rendered = _render_scout_lines(
        [
            {
                "line_id": "scout-line-1",
                "moves": ["move unit to battlefield-a", "end turn"],
                "score": 2.0,
                "risk_adjusted_score": 0.8,
                "risk_penalty": -1.2,
                "risk_adjustment_method": "pessimistic_worst",
                "opponent_windows": [{"after_move": "move unit to battlefield-a"}],
                "risk": {
                    "risk_worst": -1.2,
                    "risk_expected": -0.4,
                    "threats": [
                        {
                            "card_id": "defy",
                            "p_in_hand": 0.3,
                            "window_delta": -1.2,
                            "plan_broken": True,
                        }
                    ],
                },
            }
        ]
    )
    assert rendered[0]["risk"]["risk_worst"] == -1.2
    assert rendered[0]["risk"]["threats"][0]["card_id"] == "defy"
    assert rendered[0]["risk"]["threats"][0]["plan_broken"] is True
    assert rendered[0]["risk_adjusted_score"] == 0.8
    assert rendered[0]["risk_penalty"] == -1.2
    assert rendered[0]["risk_adjustment_method"] == "pessimistic_worst"
    assert rendered[0]["scout_rank"] == 1
    assert rendered[0]["score_note"] == "unanswered_leaf"
    # Risk ranking intentionally exposes unanswered score (with note) even when
    # RIFTBOUND_REASONER_HIDE_RAW_SCORE is on, so score + penalty is readable.
    assert rendered[0]["score"] == 2.0


def test_render_scout_lines_sorted_by_risk_adjusted():
    rendered = _render_scout_lines(
        [
            {
                "line_id": "high-raw",
                "moves": ["pass"],
                "score": 10.0,
                "risk_adjusted_score": 1.0,
                "risk_penalty": -9.0,
                "risk_adjustment_method": "expected",
            },
            {
                "line_id": "safer",
                "moves": ["pass"],
                "score": 6.0,
                "risk_adjusted_score": 5.5,
                "risk_penalty": -0.5,
                "risk_adjustment_method": "expected",
            },
        ]
    )
    assert rendered[0]["line_id"] == "safer"
    assert rendered[0]["scout_rank"] == 1
    assert rendered[1]["line_id"] == "high-raw"
