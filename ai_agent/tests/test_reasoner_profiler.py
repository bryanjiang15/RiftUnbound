"""Test that token profiling never causes a Reasoner fallback."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch

import pytest


@pytest.mark.asyncio
async def test_profiler_survives_multiple_tool_rounds(tmp_path):
    """Token profiling must work with SDK message objects over multiple rounds."""
    from pathlib import Path
    from ai_agent.reasoner import _request_reasoning
    from ai_agent.reasoner_context import ReasonerTurnContext, install_context, reset_context
    import ai_agent.agent as agent_module

    # Create a temporary log file
    log_path = tmp_path / "agent_search.log"
    original_path = agent_module._SEARCH_LOG_PATH
    original_log_inputs = agent_module._LOG_INPUTS
    agent_module._SEARCH_LOG_PATH = log_path
    agent_module._LOG_INPUTS = True

    try:
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
                "move_contexts": [
                    {"kind": "scripted"},
                    {"kind": "scripted"},
                    {"kind": "scripted"},
                ],
                "score": 2.1,
                "complete": True,
                "legal": True,
                "root_state_hash": "root_abc",
            }
        ]

        # Set up reasoner context and get canonical line ID
        context = ReasonerTurnContext(
            game_id="test-game",
            brief_state=brief_state,
            root_state_hash="root_abc",
            memory_summary="Turn 5 test",
            scout_lines=known_lines,
        )
        registered = context.registry.register_many(known_lines, source="scout")
        canonical_line_id = registered[0]["line_id"]

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
        round_0_msg.tool_calls[0].function.arguments = '{"query": "alternative lines"}'
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
        round_1_msg.tool_calls[0].function.arguments = f'{{"line_id": "{canonical_line_id}", "extra_depth": 4}}'
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
        round_2_msg.tool_calls[0].function.arguments = f'{{"line_id": "{canonical_line_id}", "rationale": "Best line from scout"}}'
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

        # Mock _invoke_traced_tool to return fake results
        def fake_invoke_tool(tool_trace, *, round_num, name, args):
            if name == "search_for":
                return json.dumps({"lines": []})
            elif name == "deepen":
                return json.dumps({"deepened_lines": []})
            return json.dumps({})

        token = install_context(context)
        try:
            with patch.object(agent_module, '_invoke_traced_tool', side_effect=fake_invoke_tool):
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

                # Assert client was called 3 times (3 tool rounds)
                assert mock_client.chat.completions.create.call_count == 3

                # Read the log and verify token_profile lines exist
                log_lines = log_path.read_text().strip().split("\n")
                profile_lines = [l for l in log_lines if "token_profile" in l]

                # Should have 3 profile lines (one per round)
                assert len(profile_lines) >= 3, f"Expected at least 3 profile lines, got {len(profile_lines)}"

                # Extract decision IDs and steps
                import re
                decision_ids = []
                steps = []
                for line in profile_lines[:3]:
                    dec_match = re.search(r"decision=(\S+)", line)
                    step_match = re.search(r"step=(\d+)", line)
                    if dec_match and step_match:
                        decision_ids.append(dec_match.group(1))
                        steps.append(int(step_match.group(1)))

                # All decision IDs should be the same
                assert len(set(decision_ids)) == 1, f"Expected one decision ID, got {set(decision_ids)}"

                # Steps should be 0, 1, 2
                assert steps == [0, 1, 2], f"Expected steps [0, 1, 2], got {steps}"

        finally:
            reset_context(token)
    finally:
        agent_module._SEARCH_LOG_PATH = original_path
        agent_module._LOG_INPUTS = original_log_inputs


@pytest.mark.asyncio
async def test_decision_id_shared_across_rounds(tmp_path):
    """Decision ID must be per decision, not per call. All rounds share one ID."""
    from pathlib import Path
    from ai_agent.reasoner import _request_reasoning
    from ai_agent.reasoner_context import ReasonerTurnContext, install_context, reset_context
    import ai_agent.agent as agent_module

    # Create a temporary log file
    log_path = tmp_path / "agent_search.log"
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
                "expected_pre_hashes": ["hash1"],
                "move_contexts": [{"kind": "scripted"}],
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

        # Mock client - simulate_move then commit_line
        mock_client = AsyncMock()

        # Round 0: model calls simulate_move
        round_0_response = Mock()
        round_0_response.choices = [Mock()]
        round_0_msg = Mock()
        round_0_msg.content = None
        round_0_msg.tool_calls = [Mock()]
        round_0_msg.tool_calls[0].id = "call_1"
        round_0_msg.tool_calls[0].type = "function"
        round_0_msg.tool_calls[0].function = Mock()
        round_0_msg.tool_calls[0].function.name = "simulate_move"
        round_0_msg.tool_calls[0].function.arguments = '{"move": "pass"}'
        round_0_response.choices[0].message = round_0_msg
        round_0_response.usage = Mock()
        round_0_response.usage.prompt_tokens = 2000
        round_0_response.usage.completion_tokens = 50
        round_0_response.usage.prompt_tokens_details = Mock()
        round_0_response.usage.prompt_tokens_details.cached_tokens = 0

        # Round 1: model calls commit_line
        round_1_response = Mock()
        round_1_response.choices = [Mock()]
        round_1_msg = Mock()
        round_1_msg.content = None
        round_1_msg.tool_calls = [Mock()]
        round_1_msg.tool_calls[0].id = "call_2"
        round_1_msg.tool_calls[0].type = "function"
        round_1_msg.tool_calls[0].function = Mock()
        round_1_msg.tool_calls[0].function.name = "commit_line"
        round_1_msg.tool_calls[0].function.arguments = f'{{"line_id": "{canonical_line_id}", "rationale": "done"}}'
        round_1_response.choices[0].message = round_1_msg
        round_1_response.usage = Mock()
        round_1_response.usage.prompt_tokens = 3000
        round_1_response.usage.completion_tokens = 40
        round_1_response.usage.prompt_tokens_details = Mock()
        round_1_response.usage.prompt_tokens_details.cached_tokens = 500

        mock_client.chat.completions.create = AsyncMock(
            side_effect=[round_0_response, round_1_response]
        )

        # Mock _invoke_traced_tool to return fake result
        def fake_invoke_tool(tool_trace, *, round_num, name, args):
            if name == "simulate_move":
                return json.dumps({"result": "ok"})
            return json.dumps({})

        token = install_context(context)
        try:
            with patch.object(agent_module, '_invoke_traced_tool', side_effect=fake_invoke_tool):
                emit = await _request_reasoning(
                    client=mock_client,
                    model="gpt-4o",
                    game_id="game-1",
                    brief_state=brief_state,
                    memory_summary="Test",
                    known_lines=known_lines,
                    root_state_hash="abc12345",
                )

                # Assert no fallback
                assert emit.kind == "line", f"Expected line commit, got {emit.kind}: {emit.rationale}"

                # Read the log and parse decision IDs
                log_lines = log_path.read_text().strip().split("\n")
                profile_lines = [l for l in log_lines if "token_profile" in l]

                # Should have at least 2 profile lines (one per round)
                assert len(profile_lines) >= 2, f"Expected at least 2 profile lines, got {len(profile_lines)}"

                # Extract decision IDs and steps
                import re
                decision_ids = []
                steps = []
                for line in profile_lines[:2]:
                    dec_match = re.search(r"decision=(\S+)", line)
                    step_match = re.search(r"step=(\d+)", line)
                    if dec_match and step_match:
                        decision_ids.append(dec_match.group(1))
                        steps.append(int(step_match.group(1)))

                # All decision IDs should be the same
                assert len(set(decision_ids)) == 1, f"Expected one decision ID, got {decision_ids}"

                # Steps should be 0, 1
                assert steps == [0, 1], f"Expected steps [0, 1], got {steps}"

                # Decision ID should be game-1-t3-rabc12345 (no -d counter)
                assert decision_ids[0] == "game-1-t3-rabc12345", f"Expected game-1-t3-rabc12345, got {decision_ids[0]}"

        finally:
            reset_context(token)
    finally:
        agent_module._SEARCH_LOG_PATH = original_path
        agent_module._LOG_INPUTS = original_log_inputs
