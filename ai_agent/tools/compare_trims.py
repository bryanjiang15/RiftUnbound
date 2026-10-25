#!/usr/bin/env python3
"""Compare Reasoner token usage with compact tools off vs on.

Usage:
    python -m ai_agent.tools.compare_trims [--repeat N] [--dry-run] [--model MODEL]

Runs a fixed set of scenarios with RIFTBOUND_REASONER_COMPACT_TOOLS=0 vs =1
and reports token counts, cost, and agreement on chosen actions.
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

logger = logging.getLogger(__name__)

# Sample scenarios (game states) to test
SCENARIOS_DIR = Path(__file__).parent.parent / "eval" / "cases"


@dataclass
class RunResult:
    """Result from one Reasoner run on one scenario."""

    scenario_id: str
    compact_enabled: bool
    prompt_tokens: int
    cached_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    steps: int
    chosen_action: str | None
    chosen_line_id: str | None
    fallback: bool
    hash_diverge: bool
    terminal_kind: str


def _parse_profile_logs(log_lines: list[str]) -> dict[str, Any]:
    """Extract token counts from token_profile log lines."""
    from ai_agent.tools.token_profile import parse_token_profile_line

    profiles = []
    for line in log_lines:
        profile = parse_token_profile_line(line)
        if profile:
            profiles.append(profile)

    if not profiles:
        return {
            "prompt_tokens": 0,
            "cached_tokens": 0,
            "completion_tokens": 0,
            "steps": 0,
        }

    total_prompt = sum(p.prompt for p in profiles)
    total_cached = sum(p.cached for p in profiles)
    total_completion = sum(p.completion for p in profiles)
    max_step = max(p.step for p in profiles) if profiles else 0

    return {
        "prompt_tokens": total_prompt,
        "cached_tokens": total_cached,
        "completion_tokens": total_completion,
        "steps": max_step + 1,
    }


def _estimate_cost(
    prompt_tokens: int, cached_tokens: int, completion_tokens: int
) -> float:
    """Estimate cost in USD using current OpenAI pricing."""
    # GPT-4o pricing per 1M tokens
    PRICE_INPUT_PER_M = 2.50
    PRICE_CACHED_PER_M = 0.25
    PRICE_OUTPUT_PER_M = 15.00

    uncached = prompt_tokens - cached_tokens
    return (
        (uncached / 1_000_000) * PRICE_INPUT_PER_M
        + (cached_tokens / 1_000_000) * PRICE_CACHED_PER_M
        + (completion_tokens / 1_000_000) * PRICE_OUTPUT_PER_M
    )


async def _run_scenario(
    scenario: dict[str, Any], compact_enabled: bool, model: str
) -> RunResult:
    """Run Reasoner on one scenario with given compact setting."""
    from openai import AsyncOpenAI

    from ai_agent.reasoner import Reasoner

    # Set env var for this run
    os.environ["RIFTBOUND_REASONER_COMPACT_TOOLS"] = "1" if compact_enabled else "0"

    client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    reasoner = Reasoner()

    scenario_id = scenario.get("scenario_id", "unknown")
    brief_state = scenario.get("brief_state", {})
    memory_summary = scenario.get("memory_summary", "")
    known_lines = scenario.get("known_lines", [])
    root_state_hash = scenario.get("root_state_hash", "")

    # Capture logs
    log_handler = logging.StreamHandler()
    log_handler.setLevel(logging.INFO)
    formatter = logging.Formatter("%(message)s")
    log_handler.setFormatter(formatter)
    reasoner_logger = logging.getLogger("ai_agent.reasoner")
    reasoner_logger.addHandler(log_handler)
    reasoner_logger.setLevel(logging.INFO)

    log_lines: list[str] = []
    original_emit = reasoner_logger._log

    def capture_log(level, msg, *args, **kwargs):
        log_lines.append(msg % args if args else msg)
        return original_emit(level, msg, *args, **kwargs)

    reasoner_logger._log = capture_log

    try:
        emit, cache_hit = await reasoner.reason(
            client=client,
            model=model,
            game_id=f"compare-{scenario_id}",
            brief_state=brief_state,
            memory_summary=memory_summary,
            known_lines=known_lines,
            root_state_hash=root_state_hash,
        )

        # Parse logs for token counts
        profile = _parse_profile_logs(log_lines)

        chosen_action = None
        chosen_line_id = None
        if emit.kind == "line":
            chosen_line_id = emit.chosen_line_id
            # Look up the line to get the first move
            for line in known_lines:
                if line.get("line_id") == chosen_line_id:
                    moves = line.get("moves", [])
                    if moves:
                        chosen_action = str(moves[0])
                    break

        return RunResult(
            scenario_id=scenario_id,
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
            chosen_action=chosen_action,
            chosen_line_id=chosen_line_id,
            fallback=emit.kind == "base_search_fallback",
            hash_diverge=False,  # Would need to check telemetry
            terminal_kind=emit.kind,
        )
    finally:
        reasoner_logger._log = original_emit
        reasoner_logger.removeHandler(log_handler)


def load_scenarios() -> list[dict[str, Any]]:
    """Load a fixed set of test scenarios.

    Uses eval cases if available, otherwise returns synthetic examples.
    """
    scenarios: list[dict[str, Any]] = []

    # Try loading from eval corpus
    if SCENARIOS_DIR.exists():
        case_files = sorted(SCENARIOS_DIR.glob("*.json"))[:12]  # Max 12
        for case_file in case_files:
            try:
                with case_file.open("r") as f:
                    case = json.load(f)
                    # Extract scenario from eval case format
                    fixture = case.get("fixture", {})
                    if fixture.get("brief_state"):
                        scenarios.append({
                            "scenario_id": case_file.stem,
                            "brief_state": fixture["brief_state"],
                            "memory_summary": fixture.get("memory_summary", ""),
                            "known_lines": fixture.get("known_lines", []),
                            "root_state_hash": fixture.get("root_state_hash", ""),
                        })
            except Exception as e:
                logger.warning(f"Failed to load {case_file}: {e}")

    if not scenarios:
        # Fallback: use synthetic minimal scenario
        scenarios.append({
            "scenario_id": "synthetic-mid-game",
            "brief_state": {
                "turn_number": 5,
                "active_player": "player",
                "phase": "main",
                "my_state": {
                    "life": 20,
                    "score": 2,
                    "hand_size": 4,
                },
                "opp_state": {
                    "life": 18,
                    "score": 1,
                },
                "legal_moves": ["play card-1", "play card-2", "pass"],
            },
            "memory_summary": "Turn 5 mid-game",
            "known_lines": [
                {
                    "line_id": "scout-0",
                    "moves": ["play card-1", "activate card-1", "end turn"],
                    "expected_pre_hashes": ["h1", "h2", "h3"],
                    "score": 2.1,
                    "complete": True,
                    "root_state_hash": "root_abc",
                },
                {
                    "line_id": "scout-1",
                    "moves": ["play card-2", "end turn"],
                    "expected_pre_hashes": ["h4", "h5"],
                    "score": 1.8,
                    "complete": True,
                    "root_state_hash": "root_abc",
                },
            ],
            "root_state_hash": "root_abc",
        })

    return scenarios


async def compare_scenarios(
    scenarios: list[dict[str, Any]], model: str, repeat: int = 1
) -> list[tuple[RunResult, RunResult]]:
    """Run each scenario with compact off and on, return paired results."""
    results: list[tuple[RunResult, RunResult]] = []

    for scenario in scenarios:
        for _ in range(repeat):
            # Run with compact off
            result_off = await _run_scenario(scenario, compact_enabled=False, model=model)
            # Run with compact on
            result_on = await _run_scenario(scenario, compact_enabled=True, model=model)

            results.append((result_off, result_on))

    return results


def format_report(results: list[tuple[RunResult, RunResult]]) -> str:
    """Generate a comparison report."""
    lines = []
    lines.append("=" * 80)
    lines.append("Reasoner Compaction Comparison Report")
    lines.append("=" * 80)
    lines.append("")

    if not results:
        lines.append("No results to compare.")
        return "\n".join(lines)

    total_prompt_off = sum(r[0].prompt_tokens for r in results)
    total_prompt_on = sum(r[1].prompt_tokens for r in results)
    total_cached_off = sum(r[0].cached_tokens for r in results)
    total_cached_on = sum(r[1].cached_tokens for r in results)
    total_completion_off = sum(r[0].completion_tokens for r in results)
    total_completion_on = sum(r[1].completion_tokens for r in results)
    total_cost_off = sum(r[0].estimated_cost_usd for r in results)
    total_cost_on = sum(r[1].estimated_cost_usd for r in results)

    lines.append(f"Total runs: {len(results)}")
    lines.append("")

    lines.append("Aggregate Totals:")
    lines.append(f"  Compact OFF: {total_prompt_off:,} prompt, {total_cached_off:,} cached, "
                 f"{total_completion_off:,} completion, ${total_cost_off:.3f}")
    lines.append(f"  Compact ON:  {total_prompt_on:,} prompt, {total_cached_on:,} cached, "
                 f"{total_completion_on:,} completion, ${total_cost_on:.3f}")
    lines.append("")

    if total_prompt_off > 0:
        prompt_savings_pct = (
            (total_prompt_off - total_prompt_on) / total_prompt_off * 100
        )
        lines.append(
            f"  Prompt token savings: {total_prompt_off - total_prompt_on:,} "
            f"({prompt_savings_pct:.1f}%)"
        )
    if total_cost_off > 0:
        cost_savings_pct = (total_cost_off - total_cost_on) / total_cost_off * 100
        lines.append(
            f"  Cost savings: ${total_cost_off - total_cost_on:.3f} "
            f"({cost_savings_pct:.1f}%)"
        )
    lines.append("")

    # Agreement on chosen action
    agreed = sum(
        1
        for off, on in results
        if off.chosen_line_id == on.chosen_line_id
        and off.chosen_line_id is not None
    )
    lines.append(
        f"Agreement on chosen line: {agreed}/{len(results)} "
        f"({agreed / len(results) * 100:.1f}%)"
    )
    lines.append("")

    lines.append("-" * 80)
    lines.append("Per-Scenario Results")
    lines.append("-" * 80)

    for off, on in results:
        lines.append(f"Scenario: {off.scenario_id}")
        lines.append(
            f"  OFF: {off.prompt_tokens:,} prompt, {off.steps} steps, "
            f"${off.estimated_cost_usd:.4f}, chosen={off.chosen_line_id or 'N/A'}"
        )
        lines.append(
            f"  ON:  {on.prompt_tokens:,} prompt, {on.steps} steps, "
            f"${on.estimated_cost_usd:.4f}, chosen={on.chosen_line_id or 'N/A'}"
        )
        agreement = "✓" if off.chosen_line_id == on.chosen_line_id else "✗"
        lines.append(f"  Agreement: {agreement}")
        lines.append("")

    return "\n".join(lines)


async def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Compare Reasoner token usage with compact tools off vs on"
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Number of times to repeat each scenario (default: 1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show scenarios that would be tested without running LLM",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4o",
        help="Model to use for testing (default: gpt-4o)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s:%(name)s:%(message)s"
    )

    scenarios = load_scenarios()

    if not scenarios:
        print("Error: no scenarios loaded", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"Would test {len(scenarios)} scenarios:")
        for scenario in scenarios:
            print(f"  - {scenario['scenario_id']}")
        return 0

    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "Error: OPENAI_API_KEY not set. Set it or use --dry-run.",
            file=sys.stderr,
        )
        return 1

    print(f"Running {len(scenarios)} scenarios with repeat={args.repeat}...")
    results = await compare_scenarios(scenarios, model=args.model, repeat=args.repeat)

    report = format_report(results)
    print(report)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
