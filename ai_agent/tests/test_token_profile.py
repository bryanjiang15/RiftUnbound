"""Tests for ai_agent/tools/token_profile.py."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ai_agent.tools.token_profile import (
    analyze_profiles,
    format_markdown_report,
    format_text_report,
    parse_log_file,
    parse_token_profile_line,
    parse_token_usage_line,
)


def test_parse_token_profile_line():
    """Parse a valid token_profile line."""
    line = (
        "INFO:ai_agent.reasoner:token_profile decision=game123 step=0 "
        "sys=1200 state=800 scout=0 assistant_hist=0 envelope=0 other=0 "
        "prompt=2000 cached=1000 completion=50"
    )
    profile = parse_token_profile_line(line)
    assert profile is not None
    assert profile.decision_id == "game123"
    assert profile.step == 0
    assert profile.sys == 1200
    assert profile.state == 800
    assert profile.scout == 0
    assert profile.assistant_hist == 0
    assert profile.envelope == 0
    assert profile.other == 0
    assert profile.tool_results_by_name == {}
    assert profile.prompt == 2000
    assert profile.cached == 1000
    assert profile.completion == 50
    assert profile.uncached_prompt == 1000


def test_parse_token_profile_line_with_tools():
    """Parse a token_profile line with tool results."""
    line = (
        "INFO:ai_agent.reasoner:token_profile decision=game456 step=2 "
        "sys=1200 state=800 scout=500 assistant_hist=500 "
        "tool:search_for=3000 tool:deepen=1500 "
        "envelope=100 other=400 "
        "prompt=7000 cached=3500 completion=100"
    )
    profile = parse_token_profile_line(line)
    assert profile is not None
    assert profile.decision_id == "game456"
    assert profile.step == 2
    assert profile.assistant_hist == 500
    assert profile.tool_results_by_name == {"search_for": 3000, "deepen": 1500}
    assert profile.prompt == 7000
    assert profile.cached == 3500
    assert profile.completion == 100


def test_parse_token_usage_line():
    """Parse a valid token_usage line."""
    line = (
        "INFO:ai_agent.reasoner:token_usage stage=reasoner_format "
        "prompt=5000 cached=2500 completion=200"
    )
    usage = parse_token_usage_line(line)
    assert usage is not None
    assert usage.stage == "reasoner_format"
    assert usage.prompt == 5000
    assert usage.cached == 2500
    assert usage.completion == 200
    assert usage.uncached_prompt == 2500


def test_parse_log_file(tmp_path: Path):
    """Parse a synthetic log file with mixed content."""
    log_path = tmp_path / "test_search.log"
    log_path.write_text(
        "INFO:other:some unrelated log line\n"
        "INFO:ai_agent.reasoner:token_profile decision=dec1 step=0 "
        "sys=1000 state=500 scout=0 assistant_hist=0 envelope=0 other=0 "
        "prompt=1500 cached=750 completion=30\n"
        "INFO:ai_agent.reasoner:token_profile decision=dec1 step=1 "
        "sys=1000 state=500 scout=200 assistant_hist=200 tool:search_for=2000 "
        "envelope=50 other=250 "
        "prompt=3700 cached=1850 completion=50\n"
        "INFO:ai_agent.reasoner:token_usage stage=reasoner_format "
        "prompt=2000 cached=1000 completion=100\n"
        "DEBUG:another module:debug line\n"
    )

    profiles, usages = parse_log_file(log_path)

    assert len(profiles) == 2
    assert profiles[0].decision_id == "dec1"
    assert profiles[0].step == 0
    assert profiles[1].step == 1
    assert profiles[1].tool_results_by_name == {"search_for": 2000}

    assert len(usages) == 1
    assert usages[0].stage == "reasoner_format"
    assert usages[0].prompt == 2000


def test_analyze_profiles_empty():
    """Handle empty input gracefully."""
    analysis = analyze_profiles([], [])
    assert analysis["total_calls"] == 0
    assert analysis["total_tokens"] == 0
    assert analysis["estimated_cost_usd"] == 0.0


def test_analyze_profiles_basic():
    """Compute basic summary stats."""
    from ai_agent.tools.token_profile import TokenProfile, TokenUsage

    profiles = [
        TokenProfile(
            decision_id="dec1",
            step=0,
            sys=1000,
            state=500,
            scout=0,
            assistant_hist=0,
            tool_results_by_name={},
            envelope=0,
            other=0,
            prompt=1500,
            cached=750,
            completion=30,
        ),
        TokenProfile(
            decision_id="dec1",
            step=1,
            sys=1000,
            state=500,
            scout=200,
            assistant_hist=200,
            tool_results_by_name={"search_for": 2000},
            envelope=50,
            other=250,
            prompt=3700,
            cached=1850,
            completion=50,
        ),
    ]

    usages = [
        TokenUsage(stage="reasoner_format", prompt=2000, cached=1000, completion=100)
    ]

    analysis = analyze_profiles(profiles, usages)

    assert analysis["total_calls"] == 3
    assert analysis["profiled_calls"] == 2
    assert analysis["unprofiled_calls"] == 1
    assert analysis["total_prompt"] == 1500 + 3700 + 2000
    assert analysis["total_cached"] == 750 + 1850 + 1000
    assert analysis["total_completion"] == 30 + 50 + 100
    assert analysis["estimated_cost_usd"] > 0

    # Check prompt share
    assert "system" in analysis["prompt_share"]
    assert "state" in analysis["prompt_share"]
    assert "assistant_hist" in analysis["prompt_share"]
    assert "tools" in analysis["prompt_share"]

    # Check step averages
    assert 0 in analysis["avg_prompt_by_step"]
    assert 1 in analysis["avg_prompt_by_step"]
    assert analysis["avg_prompt_by_step"][0] == 1500
    assert analysis["avg_prompt_by_step"][1] == 3700

    # Check tool totals
    assert analysis["tool_totals"] == {"search_for": 2000}

    # Check cached share
    assert 0 in analysis["cached_share_by_step"]
    assert 1 in analysis["cached_share_by_step"]


def test_analyze_profiles_trivial_decisions():
    """Identify trivial decisions (1-2 steps)."""
    from ai_agent.tools.token_profile import TokenProfile

    profiles = [
        TokenProfile(
            decision_id="trivial1",
            step=0,
            sys=1000,
            state=500,
            scout=0,
            assistant_hist=0,
            tool_results_by_name={},
            envelope=0,
            other=0,
            prompt=1500,
            cached=750,
            completion=30,
        ),
        TokenProfile(
            decision_id="trivial2",
            step=0,
            sys=1000,
            state=500,
            scout=0,
            assistant_hist=0,
            tool_results_by_name={},
            envelope=0,
            other=0,
            prompt=1500,
            cached=750,
            completion=30,
        ),
        TokenProfile(
            decision_id="trivial2",
            step=1,
            sys=1000,
            state=500,
            scout=0,
            assistant_hist=100,
            tool_results_by_name={},
            envelope=0,
            other=0,
            prompt=1600,
            cached=800,
            completion=40,
        ),
        TokenProfile(
            decision_id="nontrivial",
            step=0,
            sys=1000,
            state=500,
            scout=0,
            assistant_hist=0,
            tool_results_by_name={},
            envelope=0,
            other=0,
            prompt=1500,
            cached=750,
            completion=30,
        ),
        TokenProfile(
            decision_id="nontrivial",
            step=1,
            sys=1000,
            state=500,
            scout=0,
            assistant_hist=100,
            tool_results_by_name={},
            envelope=0,
            other=0,
            prompt=1600,
            cached=800,
            completion=40,
        ),
        TokenProfile(
            decision_id="nontrivial",
            step=2,
            sys=1000,
            state=500,
            scout=0,
            assistant_hist=200,
            tool_results_by_name={"search_for": 1000},
            envelope=0,
            other=0,
            prompt=2700,
            cached=1350,
            completion=60,
        ),
    ]

    analysis = analyze_profiles(profiles, [])

    assert analysis["trivial_decision_count"] == 2
    assert analysis["trivial_cost_usd"] > 0


def test_format_text_report(tmp_path: Path, capsys):
    """Generate a text report."""
    from ai_agent.tools.token_profile import TokenProfile

    profiles = [
        TokenProfile(
            decision_id="dec1",
            step=0,
            sys=1000,
            state=500,
            scout=0,
            assistant_hist=0,
            tool_results_by_name={},
            envelope=0,
            other=0,
            prompt=1500,
            cached=750,
            completion=30,
        ),
    ]

    analysis = analyze_profiles(profiles, [])

    import io

    out = io.StringIO()
    format_text_report(analysis, out)
    report = out.getvalue()

    assert "Reasoner Token Profile Report" in report
    assert "Total API calls: 1" in report
    assert "Total tokens:" in report
    assert "Estimated cost:" in report
    assert "Average prompt size by step" in report


def test_format_markdown_report(tmp_path: Path):
    """Generate a markdown report."""
    from ai_agent.tools.token_profile import TokenProfile

    profiles = [
        TokenProfile(
            decision_id="dec1",
            step=0,
            sys=1000,
            state=500,
            scout=0,
            assistant_hist=0,
            tool_results_by_name={},
            envelope=0,
            other=0,
            prompt=1500,
            cached=750,
            completion=30,
        ),
    ]

    analysis = analyze_profiles(profiles, [])

    import io

    out = io.StringIO()
    format_markdown_report(analysis, out)
    report = out.getvalue()

    assert "# Reasoner Token Profile Report" in report
    assert "## Summary" in report
    assert "**Total API calls**: 1" in report
    assert "## Average Prompt Size by Step" in report
    assert "| Step | Avg Tokens | Cached Share |" in report


def test_analyze_profiles_with_top_tool_results():
    """Test that top_tool_results is built correctly."""
    from ai_agent.tools.token_profile import TokenProfile

    profiles = [
        TokenProfile(
            decision_id="dec1",
            step=0,
            sys=1000,
            state=500,
            scout=0,
            assistant_hist=0,
            tool_results_by_name={"search_for": 5000},
            envelope=0,
            other=0,
            prompt=6500,
            cached=0,
            completion=50,
        ),
        TokenProfile(
            decision_id="dec1",
            step=1,
            sys=1000,
            state=500,
            scout=0,
            assistant_hist=200,
            tool_results_by_name={"deepen": 3000, "search_for": 2000},
            envelope=0,
            other=0,
            prompt=6700,
            cached=0,
            completion=60,
        ),
        TokenProfile(
            decision_id="dec2",
            step=0,
            sys=1000,
            state=500,
            scout=0,
            assistant_hist=0,
            tool_results_by_name={"simulate_line": 8000},
            envelope=0,
            other=0,
            prompt=9500,
            cached=0,
            completion=40,
        ),
    ]

    analysis = analyze_profiles(profiles, [])

    # Check top_tool_results exists and is sorted by token count (descending)
    assert "top_tool_results" in analysis
    top = analysis["top_tool_results"]
    assert len(top) == 4  # 4 tool results total
    
    # First should be simulate_line with 8000 tokens
    assert top[0][0] == "dec2"  # decision_id
    assert top[0][1] == "simulate_line"  # tool_name
    assert top[0][2] == 0  # step
    assert top[0][3] == 8000  # tokens
    
    # Second should be search_for with 5000 tokens
    assert top[1][3] == 5000
    assert top[1][1] == "search_for"
