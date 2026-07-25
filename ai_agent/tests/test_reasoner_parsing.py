from ai_agent.reasoner import _parse_reasoner_emit


def test_parse_direct_line_from_fenced_prose():
    emit = _parse_reasoner_emit(
        'Result:\n```json\n{"kind":"line","confidence":"commit",'
        '"moves":["pass","end turn"],"rationale":"verified"}\n```',
        turn=3,
    )
    assert emit is not None
    assert emit.kind == "line"
    assert emit.moves == ["pass", "end turn"]


def test_parse_goal_emit_drops_only_invalid_nested_goal():
    emit = _parse_reasoner_emit(
        '{"kind":"goals","confidence":"goals","goal_set":{'
        '"turn":3,"rationale":"control",'
        '"goals":['
        '{"id":"ok","kind":"weight_bias","feature":"battlefield_control"},'
        '{"id":"bad","kind":"not-a-kind"}'
        ']}}',
        turn=3,
    )
    assert emit is not None
    assert emit.goal_set is not None
    assert [goal.id for goal in emit.goal_set.goals] == ["ok"]

