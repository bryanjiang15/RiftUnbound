#!/usr/bin/env python3
"""Compare Reasoner token usage with compact tools off vs on.

Usage:
    python -m ai_agent.tools.compare_trims [--repeat N] [--model MODEL]

Requires both OPENAI_API_KEY and a running engine server.
Loads real eval positions and measures token savings with compaction on vs off.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_agent.eval.corpus import load_corpus
from ai_agent.reasoner_context import ReasonerTurnContext, install_context, reset_context

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    """Result from one Reasoner run on one scenario."""

    position_id: str
    compact_enabled: bool
    prompt_tokens: int
    cached_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    steps: int
    chosen_line_id: str | None
    terminal_kind: str
    error: str | None


def _estimate_cost(
    prompt_tokens: int, cached_tokens: int, completion_tokens: int
) -> float:
    """Estimate cost in USD using gpt-4o pricing."""
    PRICE_INPUT_PER_M = 2.50
    PRICE_CACHED_PER_M = 0.25
    PRICE_OUTPUT_PER_M = 15.00

    uncached = prompt_tokens - cached_tokens
    return (
        (uncached / 1_000_000) * PRICE_INPUT_PER_M
        + (cached_tokens / 1_000_000) * PRICE_CACHED_PER_M
        + (completion_tokens / 1_000_000) * PRICE_OUTPUT_PER_M
    )


def _parse_profile_logs(log_lines: list[str]) -> dict[str, Any]:
    """Extract token counts from token_profile log lines."""
    from ai_agent.tools.token_profile import parse_token_profile_line

    profiles = []
    for line in log_lines:
        profile = parse_token_profile_line(line)
        if profile:
            profiles.append(profile)

    if not profiles:
        return {"prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 0, "steps": 0}

    return {
        "prompt_tokens": sum(p.prompt for p in profiles),
        "cached_tokens": sum(p.cached for p in profiles),
        "completion_tokens": sum(p.completion for p in profiles),
        "steps": max(p.step for p in profiles) + 1 if profiles else 0,
    }


async def _run_position(
    position_data: dict[str, Any], compact_enabled: bool, model: str
) -> RunResult:
    """Run Reasoner on one eval position with given compact setting."""
    from openai import AsyncOpenAI
    from ai_agent import agent_module
    from ai_agent.reasoner import _request_reasoning

    os.environ["RIFTBOUND_REASONER_COMPACT_TOOLS"] = "1" if compact_enabled else "0"

    position_id = position_data["case_id"]
    fixture_path = position_data["fixture_path"]
    
    # Load fixture to get game state
    from ai_agent.eval.corpus import fixture_abs_path
    fixture_abs = fixture_abs_path(fixture_path)
    if not fixture_abs.exists():
        return RunResult(
            position_id=position_id,
            compact_enabled=compact_enabled,
            prompt_tokens=0,
            cached_tokens=0,
            completion_tokens=0,
            estimated_cost_usd=0.0,
            steps=0,
            chosen_line_id=None,
            terminal_kind="error",
            error=f"Fixture not found: {fixture_path}",
        )

    fixture = json.loads(fixture_abs.read_text())
    brief_state = fixture.get("brief_state", {})
    root_state_hash = fixture.get("root_state_hash", "")
    known_lines = fixture.get("scout_lines", [])

    if not brief_state or not root_state_hash:
        return RunResult(
            position_id=position_id,
            compact_enabled=compact_enabled,
            prompt_tokens=0,
            cached_tokens=0,
            completion_tokens=0,
            estimated_cost_usd=0.0,
            steps=0,
            chosen_line_id=None,
            terminal_kind="error",
            error="Fixture missing brief_state or root_state_hash",
        )

    # Set up context for reasoner
    context = ReasonerTurnContext(
        game_id=f"compare-{position_id}",
        brief_state=brief_state,
        root_state_hash=root_state_hash,
        memory_summary="",
        scout_lines=known_lines,
    )
    context.registry.register_many(known_lines, source="scout")
    token = install_context(context)

    # Capture logs for token profiling
    log_lines: list[str] = []
    log_handler = logging.StreamHandler()
    log_handler.setLevel(logging.INFO)
    formatter = logging.Formatter("%(message)s")
    log_handler.setFormatter(formatter)
    
    reasoner_logger = logging.getLogger("ai_agent.reasoner")
    original_level = reasoner_logger.level
    reasoner_logger.addHandler(log_handler)
    reasoner_logger.setLevel(logging.INFO)

    class LogCapture:
        def write(self, msg):
            log_lines.append(msg)
    
    log_handler.stream = LogCapture()

    try:
        client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        
        # Call reasoner with context set up
        emit, metrics, _signature = await _request_reasoning(
            client=client,
            model=model,
            turn=int(brief_state.get("turn_number", 1)),
            game_id=f"compare-{position_id}",
            root_state_hash=root_state_hash,
        )

        profile = _parse_profile_logs(log_lines)

        return RunResult(
            position_id=position_id,
            compact_enabled=compact_enabled,
            prompt_tokens=profile["prompt_tokens"],
            cached_tokens=profile["cached_tokens"],
            completion_tokens=profile["completion_tokens"],
            estimated_cost_usd=_estimate_cost(
                profile["prompt_tokens"],
                profile["cached_tokens"],
                profile["completion_tokens"],
            ),
            steps=profile["steps"],
            chosen_line_id=emit.chosen_line_id if emit.kind == "line" else None,
            terminal_kind=emit.kind,
            error=None,
        )
    except Exception as exc:
        return RunResult(
            position_id=position_id,
            compact_enabled=compact_enabled,
            prompt_tokens=0,
            cached_tokens=0,
            completion_tokens=0,
            estimated_cost_usd=0.0,
            steps=0,
            chosen_line_id=None,
            terminal_kind="error",
            error=str(exc),
        )
    finally:
        reset_context(token)
        reasoner_logger.removeHandler(log_handler)
        reasoner_logger.setLevel(original_level)


def load_test_positions(limit: int = 5) -> list[dict[str, Any]]:
    """Load a small set of eval positions for testing."""
    try:
        corpus = load_corpus(
            splits=["dev", "test"],
            eval_lanes=["reasoner"],
            include_fidelity_limited=False,
        )
        # Filter to positions that are reasonable for comparison
        suitable = [
            case.model_dump()
            for case in corpus
            if case.decision_type in {"main_phase", "reactive"}
            and case.difficulty in {"easy", "medium"}
        ]
        return suitable[:limit]
    except Exception as e:
        logger.warning(f"Failed to load corpus: {e}")
        return []


def format_report(results: list[tuple[RunResult, RunResult]]) -> str:
    """Generate a comparison report."""
    lines = ["=" * 80, "Reasoner Compaction Comparison Report", "=" * 80, ""]

    if not results:
        lines.append("No results to compare.")
        return "\n".join(lines)

    # Filter out errors
    valid = [(off, on) for off, on in results if off.error is None and on.error is None]
    if not valid:
        lines.append("All runs failed. Check OPENAI_API_KEY and engine server.")
        return "\n".join(lines)

    total_prompt_off = sum(r[0].prompt_tokens for r in valid)
    total_prompt_on = sum(r[1].prompt_tokens for r in valid)
    total_cached_off = sum(r[0].cached_tokens for r in valid)
    total_cached_on = sum(r[1].cached_tokens for r in valid)
    total_cost_off = sum(r[0].estimated_cost_usd for r in valid)
    total_cost_on = sum(r[1].estimated_cost_usd for r in valid)

    lines.append(f"Valid runs: {len(valid)}/{len(results)}")
    lines.append("")
    lines.append("PROJECTION (from limited sample):")
    lines.append(
        f"  Compact OFF: {total_prompt_off:,} prompt ({total_cached_off:,} cached), ${total_cost_off:.3f}"
    )
    lines.append(
        f"  Compact ON:  {total_prompt_on:,} prompt ({total_cached_on:,} cached), ${total_cost_on:.3f}"
    )

    if total_prompt_off > 0:
        savings_pct = (total_prompt_off - total_prompt_on) / total_prompt_off * 100
        lines.append(f"  Prompt savings: {total_prompt_off - total_prompt_on:,} ({savings_pct:.1f}%)")

    if total_cost_off > 0:
        cost_savings_pct = (total_cost_off - total_cost_on) / total_cost_off * 100
        lines.append(f"  Cost savings: ${total_cost_off - total_cost_on:.3f} ({cost_savings_pct:.1f}%)")

    agreed = sum(
        1 for off, on in valid if off.chosen_line_id == on.chosen_line_id and off.chosen_line_id is not None
    )
    lines.append("")
    lines.append(f"Agreement: {agreed}/{len(valid)} ({agreed / len(valid) * 100:.1f}%)")
    lines.append("")
    lines.append("-" * 80)
    lines.append("Per-Position Results")
    lines.append("-" * 80)

    for off, on in results:
        lines.append(f"Position: {off.position_id}")
        if off.error:
            lines.append(f"  OFF: Error - {off.error}")
        else:
            lines.append(
                f"  OFF: {off.prompt_tokens:,} prompt, {off.steps} steps, ${off.estimated_cost_usd:.4f}, line={off.chosen_line_id or 'N/A'}"
            )
        if on.error:
            lines.append(f"  ON:  Error - {on.error}")
        else:
            lines.append(
                f"  ON:  {on.prompt_tokens:,} prompt, {on.steps} steps, ${on.estimated_cost_usd:.4f}, line={on.chosen_line_id or 'N/A'}"
            )
        if off.error is None and on.error is None:
            agreement = "✓" if off.chosen_line_id == on.chosen_line_id else "✗"
            lines.append(f"  Agreement: {agreement}")
        lines.append("")

    return "\n".join(lines)


async def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Compare Reasoner token usage")
    parser.add_argument("--repeat", type=int, default=1, help="Repeats per position (default: 1)")
    parser.add_argument("--model", type=str, default="gpt-4o", help="Model to use (default: gpt-4o)")
    parser.add_argument("--positions", type=int, default=3, help="Number of positions to test (default: 3)")

    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s:%(name)s:%(message)s")

    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY not set.", file=sys.stderr)
        return 1

    positions = load_test_positions(limit=args.positions)
    if not positions:
        print("Error: No eval positions loaded. Check Data/AI/Eval/positions/", file=sys.stderr)
        return 1

    print(f"Testing {len(positions)} positions with {args.repeat} repeats each...")
    print("Note: Requires engine server running (see Data/AI/Baseline/README.md)")
    print("")

    results: list[tuple[RunResult, RunResult]] = []
    for position in positions:
        for _ in range(args.repeat):
            result_off = await _run_position(position, compact_enabled=False, model=args.model)
            result_on = await _run_position(position, compact_enabled=True, model=args.model)
            results.append((result_off, result_on))

    report = format_report(results)
    print(report)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
