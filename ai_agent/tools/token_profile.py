#!/usr/bin/env python3
"""Parse Reasoner token profile logs and generate cost/composition reports.

Usage:
    python -m ai_agent.tools.token_profile [log_path]
    python -m ai_agent.tools.token_profile --markdown [log_path]

Parses `token_profile` and `token_usage` log lines from agent_search.log
(default path: ai_agent/agent_search.log) and produces a cost breakdown:
- Total tokens and estimated cost
- Average prompt size by step number (to show growth within decisions)
- Share of prompt tokens by section (system, state, assistant history, tools)
- Top 10 largest tool results
- Trivial decision stats (single legal action or 1-2 step decisions)
- Cached token share per step
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


@dataclass
class TokenProfile:
    """One token profile measurement from a Reasoner step."""

    decision_id: str
    step: int
    sys: int
    state: int
    assistant_hist: int
    tool_results_by_name: dict[str, int]
    prompt: int
    cached: int
    completion: int

    @property
    def uncached_prompt(self) -> int:
        return self.prompt - self.cached


@dataclass
class TokenUsage:
    """Simple token usage measurement (non-profiled calls)."""

    stage: str
    prompt: int
    cached: int
    completion: int

    @property
    def uncached_prompt(self) -> int:
        return self.prompt - self.cached


# OpenAI GPT pricing (per 1M tokens) as of context date
PRICE_INPUT_PER_M = 2.50
PRICE_CACHED_PER_M = 0.25
PRICE_OUTPUT_PER_M = 15.00


def parse_token_profile_line(line: str) -> TokenProfile | None:
    """Parse one token_profile log line."""
    if "token_profile" not in line:
        return None

    match = re.search(
        r"token_profile decision=(\S+) step=(\d+) "
        r"sys=(\d+) state=(\d+) assistant_hist=(\d+) "
        r"(.*?)prompt=(\d+) cached=(\d+) completion=(\d+)",
        line,
    )
    if not match:
        return None

    decision_id = match.group(1)
    step = int(match.group(2))
    sys = int(match.group(3))
    state = int(match.group(4))
    assistant_hist = int(match.group(5))
    tool_part = match.group(6).strip()
    prompt = int(match.group(7))
    cached = int(match.group(8))
    completion = int(match.group(9))

    tool_results_by_name: dict[str, int] = {}
    if tool_part:
        for tool_match in re.finditer(r"tool:(\S+?)=(\d+)", tool_part):
            tool_name = tool_match.group(1)
            tokens = int(tool_match.group(2))
            tool_results_by_name[tool_name] = tool_results_by_name.get(tool_name, 0) + tokens

    return TokenProfile(
        decision_id=decision_id,
        step=step,
        sys=sys,
        state=state,
        assistant_hist=assistant_hist,
        tool_results_by_name=tool_results_by_name,
        prompt=prompt,
        cached=cached,
        completion=completion,
    )


def parse_token_usage_line(line: str) -> TokenUsage | None:
    """Parse one token_usage log line."""
    if "token_usage" not in line:
        return None

    match = re.search(
        r"token_usage stage=(\S+) prompt=(\d+) cached=(\d+) completion=(\d+)",
        line,
    )
    if not match:
        return None

    return TokenUsage(
        stage=match.group(1),
        prompt=int(match.group(2)),
        cached=int(match.group(3)),
        completion=int(match.group(4)),
    )


def parse_log_file(log_path: Path) -> tuple[list[TokenProfile], list[TokenUsage]]:
    """Parse all token profile and usage lines from a log file."""
    profiles: list[TokenProfile] = []
    usages: list[TokenUsage] = []

    with log_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            profile = parse_token_profile_line(line)
            if profile:
                profiles.append(profile)
                continue

            usage = parse_token_usage_line(line)
            if usage:
                usages.append(usage)

    return profiles, usages


def analyze_profiles(
    profiles: list[TokenProfile], usages: list[TokenUsage]
) -> dict:
    """Compute summary statistics from token profiles."""
    if not profiles and not usages:
        return {
            "total_calls": 0,
            "total_tokens": 0,
            "total_prompt": 0,
            "total_cached": 0,
            "total_uncached_prompt": 0,
            "total_completion": 0,
            "estimated_cost_usd": 0.0,
        }

    total_prompt = sum(p.prompt for p in profiles) + sum(u.prompt for u in usages)
    total_cached = sum(p.cached for p in profiles) + sum(u.cached for u in usages)
    total_uncached_prompt = (
        sum(p.uncached_prompt for p in profiles)
        + sum(u.uncached_prompt for u in usages)
    )
    total_completion = sum(p.completion for p in profiles) + sum(
        u.completion for u in usages
    )
    total_tokens = total_prompt + total_completion

    cost_usd = (
        (total_uncached_prompt / 1_000_000) * PRICE_INPUT_PER_M
        + (total_cached / 1_000_000) * PRICE_CACHED_PER_M
        + (total_completion / 1_000_000) * PRICE_OUTPUT_PER_M
    )

    # Average prompt size by step number
    prompt_by_step: dict[int, list[int]] = defaultdict(list)
    for p in profiles:
        prompt_by_step[p.step].append(p.prompt)

    avg_prompt_by_step = {
        step: sum(prompts) / len(prompts) if prompts else 0
        for step, prompts in sorted(prompt_by_step.items())
    }

    # Share of prompt tokens by section (only from profiled calls)
    total_sys = sum(p.sys for p in profiles)
    total_state = sum(p.state for p in profiles)
    total_assistant_hist = sum(p.assistant_hist for p in profiles)
    tool_totals: dict[str, int] = defaultdict(int)
    for p in profiles:
        for tool_name, tokens in p.tool_results_by_name.items():
            tool_totals[tool_name] += tokens
    total_tools = sum(tool_totals.values())

    profiled_prompt = sum(p.prompt for p in profiles)
    prompt_share = {}
    if profiled_prompt > 0:
        prompt_share["system"] = total_sys / profiled_prompt
        prompt_share["state"] = total_state / profiled_prompt
        prompt_share["assistant_hist"] = total_assistant_hist / profiled_prompt
        prompt_share["tools"] = total_tools / profiled_prompt

    # Top 10 largest tool results
    all_tool_results: list[tuple[str, str, int, int]] = []
    for p in profiles:
        for tool_name, tokens in p.tool_results_by_name.items():
            all_tool_results.append((p.decision_id, tool_name, p.step, tokens))
    top_tool_results = sorted(all_tool_results, key=lambda x: x[3], reverse=True)[:10]

    # Trivial decisions (1-2 steps)
    decisions_by_id: dict[str, list[TokenProfile]] = defaultdict(list)
    for p in profiles:
        decisions_by_id[p.decision_id].append(p)

    trivial_decisions = []
    trivial_cost_usd = 0.0
    for decision_id, steps in decisions_by_id.items():
        if len(steps) <= 2:
            decision_prompt = sum(s.prompt for s in steps)
            decision_cached = sum(s.cached for s in steps)
            decision_uncached = sum(s.uncached_prompt for s in steps)
            decision_completion = sum(s.completion for s in steps)
            decision_cost = (
                (decision_uncached / 1_000_000) * PRICE_INPUT_PER_M
                + (decision_cached / 1_000_000) * PRICE_CACHED_PER_M
                + (decision_completion / 1_000_000) * PRICE_OUTPUT_PER_M
            )
            trivial_decisions.append(
                {
                    "decision_id": decision_id,
                    "steps": len(steps),
                    "prompt": decision_prompt,
                    "cached": decision_cached,
                    "completion": decision_completion,
                    "cost_usd": decision_cost,
                }
            )
            trivial_cost_usd += decision_cost

    # Cached share per step
    cached_share_by_step = {}
    for step, prompts in prompt_by_step.items():
        step_profiles = [p for p in profiles if p.step == step]
        step_cached = sum(p.cached for p in step_profiles)
        step_prompt = sum(p.prompt for p in step_profiles)
        cached_share_by_step[step] = (
            step_cached / step_prompt if step_prompt > 0 else 0
        )

    return {
        "total_calls": len(profiles) + len(usages),
        "profiled_calls": len(profiles),
        "unprofiled_calls": len(usages),
        "total_tokens": total_tokens,
        "total_prompt": total_prompt,
        "total_cached": total_cached,
        "total_uncached_prompt": total_uncached_prompt,
        "total_completion": total_completion,
        "estimated_cost_usd": cost_usd,
        "avg_prompt_by_step": avg_prompt_by_step,
        "prompt_share": prompt_share,
        "tool_totals": dict(tool_totals),
        "top_tool_results": top_tool_results,
        "trivial_decisions": trivial_decisions,
        "trivial_decision_count": len(trivial_decisions),
        "trivial_cost_usd": trivial_cost_usd,
        "cached_share_by_step": cached_share_by_step,
    }


def format_text_report(analysis: dict, out: TextIO) -> None:
    """Write a human-readable text report."""
    out.write("=" * 80 + "\n")
    out.write("Reasoner Token Profile Report\n")
    out.write("=" * 80 + "\n\n")

    out.write(f"Total API calls: {analysis['total_calls']}\n")
    out.write(f"  Profiled: {analysis['profiled_calls']}\n")
    out.write(f"  Unprofiled: {analysis['unprofiled_calls']}\n\n")

    out.write(f"Total tokens: {analysis['total_tokens']:,}\n")
    out.write(f"  Prompt: {analysis['total_prompt']:,}\n")
    out.write(f"    Uncached: {analysis['total_uncached_prompt']:,}\n")
    out.write(f"    Cached: {analysis['total_cached']:,}\n")
    out.write(
        f"    Cache hit rate: {analysis['total_cached'] / analysis['total_prompt']:.1%}\n"
        if analysis["total_prompt"] > 0
        else ""
    )
    out.write(f"  Completion: {analysis['total_completion']:,}\n\n")

    out.write(
        f"Estimated cost: ${analysis['estimated_cost_usd']:.2f}\n"
    )
    out.write(
        f"  (input ${PRICE_INPUT_PER_M}/1M, "
        f"cached ${PRICE_CACHED_PER_M}/1M, "
        f"output ${PRICE_OUTPUT_PER_M}/1M)\n\n"
    )

    out.write("-" * 80 + "\n")
    out.write("Average prompt size by step (within decisions)\n")
    out.write("-" * 80 + "\n")
    for step, avg in sorted(analysis["avg_prompt_by_step"].items()):
        cached_share = analysis["cached_share_by_step"].get(step, 0)
        out.write(f"  Step {step}: {avg:,.0f} tokens (cached {cached_share:.1%})\n")
    out.write("\n")

    out.write("-" * 80 + "\n")
    out.write("Prompt composition share (from profiled calls)\n")
    out.write("-" * 80 + "\n")
    for section, share in sorted(analysis["prompt_share"].items(), key=lambda x: -x[1]):
        out.write(f"  {section:20s}: {share:6.1%}\n")
    out.write("\n")

    out.write("-" * 80 + "\n")
    out.write("Tool result token totals\n")
    out.write("-" * 80 + "\n")
    for tool_name, tokens in sorted(
        analysis["tool_totals"].items(), key=lambda x: -x[1]
    ):
        out.write(f"  {tool_name:30s}: {tokens:,} tokens\n")
    out.write("\n")

    out.write("-" * 80 + "\n")
    out.write("Top 10 largest single tool results\n")
    out.write("-" * 80 + "\n")
    for decision_id, tool_name, step, tokens in analysis["top_tool_results"]:
        out.write(
            f"  {decision_id} step {step:2d} {tool_name:20s}: {tokens:,} tokens\n"
        )
    out.write("\n")

    out.write("-" * 80 + "\n")
    out.write("Trivial decisions (1-2 steps)\n")
    out.write("-" * 80 + "\n")
    out.write(f"Count: {analysis['trivial_decision_count']}\n")
    out.write(f"Total cost: ${analysis['trivial_cost_usd']:.2f}\n")
    if analysis["trivial_decisions"]:
        out.write("\nExamples:\n")
        for td in analysis["trivial_decisions"][:5]:
            out.write(
                f"  {td['decision_id']} ({td['steps']} steps): "
                f"{td['prompt']:,} prompt, {td['completion']:,} completion, "
                f"${td['cost_usd']:.3f}\n"
            )
    out.write("\n")


def format_markdown_report(analysis: dict, out: TextIO) -> None:
    """Write a markdown report."""
    out.write("# Reasoner Token Profile Report\n\n")

    out.write("## Summary\n\n")
    out.write(f"- **Total API calls**: {analysis['total_calls']}\n")
    out.write(f"  - Profiled: {analysis['profiled_calls']}\n")
    out.write(f"  - Unprofiled: {analysis['unprofiled_calls']}\n")
    out.write(f"- **Total tokens**: {analysis['total_tokens']:,}\n")
    out.write(f"  - Prompt: {analysis['total_prompt']:,}\n")
    out.write(f"    - Uncached: {analysis['total_uncached_prompt']:,}\n")
    out.write(f"    - Cached: {analysis['total_cached']:,}\n")
    if analysis["total_prompt"] > 0:
        out.write(
            f"    - Cache hit rate: "
            f"{analysis['total_cached'] / analysis['total_prompt']:.1%}\n"
        )
    out.write(f"  - Completion: {analysis['total_completion']:,}\n")
    out.write(
        f"- **Estimated cost**: ${analysis['estimated_cost_usd']:.2f}\n"
    )
    out.write(
        f"  - Pricing: input ${PRICE_INPUT_PER_M}/1M, "
        f"cached ${PRICE_CACHED_PER_M}/1M, "
        f"output ${PRICE_OUTPUT_PER_M}/1M\n\n"
    )

    out.write("## Average Prompt Size by Step\n\n")
    out.write("| Step | Avg Tokens | Cached Share |\n")
    out.write("|-----:|-----------:|-------------:|\n")
    for step, avg in sorted(analysis["avg_prompt_by_step"].items()):
        cached_share = analysis["cached_share_by_step"].get(step, 0)
        out.write(f"| {step} | {avg:,.0f} | {cached_share:.1%} |\n")
    out.write("\n")

    out.write("## Prompt Composition (Profiled Calls)\n\n")
    out.write("| Section | Share |\n")
    out.write("|:--------|------:|\n")
    for section, share in sorted(analysis["prompt_share"].items(), key=lambda x: -x[1]):
        out.write(f"| {section} | {share:.1%} |\n")
    out.write("\n")

    out.write("## Tool Result Token Totals\n\n")
    out.write("| Tool Name | Total Tokens |\n")
    out.write("|:----------|-------------:|\n")
    for tool_name, tokens in sorted(
        analysis["tool_totals"].items(), key=lambda x: -x[1]
    ):
        out.write(f"| `{tool_name}` | {tokens:,} |\n")
    out.write("\n")

    out.write("## Top 10 Largest Tool Results\n\n")
    out.write("| Decision | Step | Tool | Tokens |\n")
    out.write("|:---------|-----:|:-----|-------:|\n")
    for decision_id, tool_name, step, tokens in analysis["top_tool_results"]:
        out.write(f"| `{decision_id}` | {step} | `{tool_name}` | {tokens:,} |\n")
    out.write("\n")

    out.write("## Trivial Decisions (1-2 steps)\n\n")
    out.write(f"- **Count**: {analysis['trivial_decision_count']}\n")
    out.write(f"- **Total cost**: ${analysis['trivial_cost_usd']:.2f}\n\n")
    if analysis["trivial_decisions"]:
        out.write("### Examples\n\n")
        out.write("| Decision | Steps | Prompt | Completion | Cost |\n")
        out.write("|:---------|------:|-------:|-----------:|-----:|\n")
        for td in analysis["trivial_decisions"][:5]:
            out.write(
                f"| `{td['decision_id']}` | {td['steps']} | "
                f"{td['prompt']:,} | {td['completion']:,} | "
                f"${td['cost_usd']:.3f} |\n"
            )
    out.write("\n")


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Parse Reasoner token profile logs and generate reports"
    )
    parser.add_argument(
        "log_path",
        type=Path,
        nargs="?",
        default=Path(__file__).resolve().parent.parent / "agent_search.log",
        help="Path to agent_search.log (default: ai_agent/agent_search.log)",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Output markdown format instead of plain text",
    )

    args = parser.parse_args()

    if not args.log_path.exists():
        print(f"Error: log file not found: {args.log_path}", file=sys.stderr)
        return 1

    profiles, usages = parse_log_file(args.log_path)

    if not profiles and not usages:
        print(
            f"Warning: no token profile or usage lines found in {args.log_path}",
            file=sys.stderr,
        )
        return 0

    analysis = analyze_profiles(profiles, usages)

    if args.markdown:
        format_markdown_report(analysis, sys.stdout)
    else:
        format_text_report(analysis, sys.stdout)

    return 0


if __name__ == "__main__":
    sys.exit(main())
