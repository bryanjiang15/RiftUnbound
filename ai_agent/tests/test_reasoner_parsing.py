from ai_agent.reasoner import _parse_reasoner_emit


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
