"""Test that token profiling never causes a Reasoner fallback."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.asyncio
async def test_profiler_survives_multiple_tool_rounds():
    """Token profiling must work with SDK message objects over multiple rounds."""
    from ai_agent.reasoner import _request_reasoning

    # Mock client that returns SDK-like responses
    mock_client = AsyncMock()

    # Round 0: model calls search_for
    round_0_response = Mock()
    round_0_response.choices = [Mock()]
    round_0_msg = Mock()
    round_0_msg.content = None
    round_0_msg.tool_calls = [Mock()]
    round_0_msg.tool_calls[0].id = "call_1"
    round_0_msg.tool_calls[0].type = "function"
    round_0_msg.tool_calls[0].function = Mock()
    round_0_msg.tool_calls[0].function.name = "search_for"
    round_0_msg.tool_calls[0].function.arguments = '{"query": "best line"}'
    round_0_response.choices[0].message = round_0_msg
    round_0_response.usage = Mock()
    round_0_response.usage.prompt_tokens = 2500
    round_0_response.usage.completion_tokens = 50
    round_0_response.usage.prompt_tokens_details = Mock()
    round_0_response.usage.prompt_tokens_details.cached_tokens = 0

    # Round 1: model calls deepen
    round_1_response = Mock()
    round_1_response.choices = [Mock()]
    round_1_msg = Mock()
    round_1_msg.content = None
    round_1_msg.tool_calls = [Mock()]
    round_1_msg.tool_calls[0].id = "call_2"
    round_1_msg.tool_calls[0].type = "function"
    round_1_msg.tool_calls[0].function = Mock()
    round_1_msg.tool_calls[0].function.name = "deepen"
    round_1_msg.tool_calls[0].function.arguments = '{"line_id": "scout-0", "extra_depth": 4}'
    round_1_response.choices[0].message = round_1_msg
    round_1_response.usage = Mock()
    round_1_response.usage.prompt_tokens = 6000
    round_1_response.usage.completion_tokens = 60
    round_1_response.usage.prompt_tokens_details = Mock()
    round_1_response.usage.prompt_tokens_details.cached_tokens = 1200

    # Round 2: model calls commit_line
    round_2_response = Mock()
    round_2_response.choices = [Mock()]
    round_2_msg = Mock()
    round_2_msg.content = None
    round_2_msg.tool_calls = [Mock()]
    round_2_msg.tool_calls[0].id = "call_3"
    round_2_msg.tool_calls[0].type = "function"
    round_2_msg.tool_calls[0].function = Mock()
    round_2_msg.tool_calls[0].function.name = "commit_line"
    round_2_msg.tool_calls[0].function.arguments = '{"line_id": "scout-0", "rationale": "Best line"}'
    round_2_response.choices[0].message = round_2_msg
    round_2_response.usage = Mock()
    round_2_response.usage.prompt_tokens = 8500
    round_2_response.usage.completion_tokens = 40
    round_2_response.usage.prompt_tokens_details = Mock()
    round_2_response.usage.prompt_tokens_details.cached_tokens = 5000

    # Mock client returns responses in sequence
    mock_client.chat.completions.create = AsyncMock(
        side_effect=[round_0_response, round_1_response, round_2_response]
    )

    # Minimal brief state with one legal move
    brief_state = {
        "turn_number": 5,
        "active_player": "player",
        "phase": "main",
        "my_state": {"life": 20, "score": 2},
        "opp_state": {"life": 18, "score": 1},
        "legal_moves": ["play card-1", "pass"],
    }

    # Scout baseline with one complete line
    known_lines = [
        {
            "line_id": "scout-0",
            "moves": ["play card-1", "activate card-1", "end turn"],
            "expected_pre_hashes": ["hash1", "hash2", "hash3"],
            "score": 2.1,
            "complete": True,
            "legal": True,
            "root_state_hash": "root_abc",
        }
    ]

    # Set up reasoner context
    from ai_agent.reasoner_context import ReasonerContext

    context = ReasonerContext()
    context.registry.register_many(known_lines, source="scout")
    context.scout_lines = known_lines

    # Use context manager to set current context
    from ai_agent.reasoner_context import _context_var

    token = _context_var.set(context)
    try:
        emit, cache_hit = await _request_reasoning(
            client=mock_client,
            model="gpt-4o",
            game_id="test-game",
            brief_state=brief_state,
            memory_summary="Turn 5 test",
            known_lines=known_lines,
            root_state_hash="root_abc",
        )

        # Assert no fallback (emit kind should be "line", not "base_search_fallback")
        assert emit.kind == "line", f"Expected line commit, got {emit.kind}: {emit.rationale}"
        assert emit.chosen_line_id == "scout-0"
        assert "fallback" not in emit.rationale.lower()

        # Assert client was called 3 times (3 tool rounds)
        assert mock_client.chat.completions.create.call_count == 3

    finally:
        _context_var.reset(token)


@pytest.mark.asyncio
async def test_profiler_handles_dict_and_sdk_messages():
    """Profiling must handle both dict messages (our format) and SDK objects (model replies)."""
    from ai_agent.reasoner import _estimate_tokens

    # Simulate a message list with mixed types
    class MockSDKMessage:
        def __init__(self, role: str, content: str | None):
            self.role = role
            self.content = content

    messages = [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "User message"},
        MockSDKMessage("assistant", "Assistant reply"),
        {"role": "tool", "tool_call_id": "call_1", "content": '{"result": "data"}'},
    ]

    # Should not crash when profiling tries to iterate
    total = 0
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("role", "")
            content = msg.get("content")
        else:
            role = getattr(msg, "role", "")
            content = getattr(msg, "content", None)

        if content:
            total += _estimate_tokens(str(content))

    assert total > 0, "Should have counted some tokens"
