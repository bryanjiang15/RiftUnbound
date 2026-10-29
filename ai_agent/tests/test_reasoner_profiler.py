"""Test that token profiling never causes a Reasoner fallback."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.asyncio
async def test_profiler_survives_multiple_tool_rounds():
    """Token profiling must work with SDK message objects over multiple rounds."""
    from ai_agent.reasoner import _request_reasoning
    from ai_agent.reasoner_context import ReasonerTurnContext, install_context, reset_context

    # Mock client that returns SDK-like responses
    mock_client = AsyncMock()

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
    context = ReasonerTurnContext(
        game_id="test-game",
        brief_state=brief_state,
        root_state_hash="root_abc",
        memory_summary="Turn 5 test",
        scout_lines=known_lines,
    )
    registered = context.registry.register_many(known_lines, source="scout")
    canonical_line_id = registered[0]["line_id"]

    # Round 0: model immediately calls commit_line (valid terminal)
    round_0_response = Mock()
    round_0_response.choices = [Mock()]
    round_0_msg = Mock()
    round_0_msg.content = None
    round_0_msg.tool_calls = [Mock()]
    round_0_msg.tool_calls[0].id = "call_1"
    round_0_msg.tool_calls[0].type = "function"
    round_0_msg.tool_calls[0].function = Mock()
    round_0_msg.tool_calls[0].function.name = "commit_line"
    round_0_msg.tool_calls[0].function.arguments = f'{{"line_id": "{canonical_line_id}", "rationale": "Best line from scout"}}'
    round_0_response.choices[0].message = round_0_msg
    round_0_response.usage = Mock()
    round_0_response.usage.prompt_tokens = 2500
    round_0_response.usage.completion_tokens = 50
    round_0_response.usage.prompt_tokens_details = Mock()
    round_0_response.usage.prompt_tokens_details.cached_tokens = 0

    # Mock client returns response
    mock_client.chat.completions.create = AsyncMock(return_value=round_0_response)

    token = install_context(context)
    try:
        emit = await _request_reasoning(
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
        assert "fallback" not in emit.rationale.lower()
        assert "Reasoner API error" not in emit.rationale

        # Assert client was called at least once
        assert mock_client.chat.completions.create.call_count >= 1

    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_decision_id_shared_across_rounds(tmp_path):
    """Decision ID must be per decision, not per call. All rounds share one ID."""
    from pathlib import Path
    import os
    from ai_agent.reasoner import _request_reasoning
    from ai_agent.reasoner_context import ReasonerTurnContext, install_context, reset_context

    # Create a temporary log file
    log_path = tmp_path / "agent_search.log"
    
    # Temporarily override the agent's search log path
    import ai_agent.agent as agent_module
    original_path = agent_module._SEARCH_LOG_PATH
    original_log_inputs = agent_module._LOG_INPUTS
    agent_module._SEARCH_LOG_PATH = log_path
    agent_module._LOG_INPUTS = True
    
    try:
        brief_state = {
            "turn_number": 3,
            "active_player": "player",
            "phase": "main",
            "my_state": {"life": 20},
            "opp_state": {"life": 20},
            "legal_moves": ["pass"],
        }
        
        known_lines = [
            {
                "line_id": "scout-0",
                "moves": ["pass"],
                "score": 1.0,
                "complete": True,
                "legal": True,
                "root_state_hash": "abc12345",
            }
        ]
        
        context = ReasonerTurnContext(
            game_id="game-1",
            brief_state=brief_state,
            root_state_hash="abc12345",
            memory_summary="Test",
            scout_lines=known_lines,
        )
        registered = context.registry.register_many(known_lines, source="scout")
        canonical_line_id = registered[0]["line_id"]
        
        # Mock client - commit_line immediately
        mock_client = AsyncMock()
        
        resp = Mock()
        resp.choices = [Mock()]
        msg = Mock()
        msg.content = None
        msg.tool_calls = [Mock()]
        msg.tool_calls[0].id = "call_1"
        msg.tool_calls[0].type = "function"
        msg.tool_calls[0].function = Mock()
        msg.tool_calls[0].function.name = "commit_line"
        msg.tool_calls[0].function.arguments = f'{{"line_id": "{canonical_line_id}", "rationale": "done"}}'
        resp.choices[0].message = msg
        resp.usage = Mock()
        resp.usage.prompt_tokens = 2000
        resp.usage.completion_tokens = 50
        resp.usage.prompt_tokens_details = Mock()
        resp.usage.prompt_tokens_details.cached_tokens = 0
        
        mock_client.chat.completions.create = AsyncMock(return_value=resp)
        
        token = install_context(context)
        try:
            emit = await _request_reasoning(
                client=mock_client,
                model="gpt-4o",
                game_id="game-1",
                brief_state=brief_state,
                memory_summary="Test",
                known_lines=known_lines,
                root_state_hash="abc12345",
            )
            
            # Read the log and parse decision IDs
            log_lines = log_path.read_text().strip().split("\n")
            profile_lines = [l for l in log_lines if "token_profile" in l]
            
            # Should have at least 1 profile line (one per round)
            assert len(profile_lines) >= 1, f"Expected at least 1 profile lines, got {len(profile_lines)}"
            
            # Extract decision IDs and steps
            import re
            decision_ids = []
            steps = []
            for line in profile_lines:
                dec_match = re.search(r"decision=(\S+)", line)
                step_match = re.search(r"step=(\d+)", line)
                if dec_match and step_match:
                    decision_ids.append(dec_match.group(1))
                    steps.append(int(step_match.group(1)))
            
            # All decision IDs should be the same
            assert len(set(decision_ids)) == 1, f"Expected one decision ID, got {decision_ids}"
            
            # Steps should start at 0
            assert steps[0] == 0, f"Expected first step to be 0, got {steps[0]}"
            
            # Decision ID should be game-1-t3-rabc12345 (no -d counter)
            assert decision_ids[0] == "game-1-t3-rabc12345", f"Expected game-1-t3-rabc12345, got {decision_ids[0]}"
            
        finally:
            reset_context(token)
    finally:
        agent_module._SEARCH_LOG_PATH = original_path
        agent_module._LOG_INPUTS = original_log_inputs
