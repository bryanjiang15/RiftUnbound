"""
Riftbound AI Agent — Reasoning Loop

This module owns the ~150-line loop that:
  1. Assembles context from system prompt, memory, and brief state.
  2. Calls the OpenAI chat completions API with the skill tool set.
  3. Dispatches any tool calls the model makes (read / helper skills).
  4. Validates that the final output conforms to the Decision schema.
  5. Falls back to "pass" after MAX_TOOL_ROUNDS or on unrecoverable error.

The loop is intentionally kept explicit and debuggable — no framework magic.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from openai.types.chat import ChatCompletionMessageParam

from . import planner as planner_module
from . import router as router_module
from . import skills as skill_module
from . import strategist as strategist_module
from .goal_compiler import ProfileOverlay, compile_goals, overlay_delta, overlay_delta_breakdown
from .memory import Memory
from .schemas import CandidateLine, Decision, GoalSet, LegalActionOption, Move, Plan, SearchStats
from .system_prompt import build_system_prompt, build_system_prompt_from_modules

logger = logging.getLogger(__name__)

# Transient API failures worth retrying in-loop with backoff (rather than
# instantly falling back to pass). A 429 rate limit is the common one; timeouts,
# connection drops, and 5xx are also recoverable.
TRANSIENT_API_ERRORS = (
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
)

# How many times to retry a single transient-failing API call before giving up.
# Bounded so we never blow past Godot's client-side decision timeout.
MAX_TRANSIENT_RETRIES = int(os.environ.get("RIFTBOUND_TRANSIENT_RETRIES", "3"))
# Base seconds for exponential backoff between transient retries.
TRANSIENT_BACKOFF_BASE_S = float(os.environ.get("RIFTBOUND_TRANSIENT_BACKOFF_S", "1.0"))

_INPUT_LOG_PATH = Path(__file__).resolve().parent / "agent_inputs.log"
_PLAN_LOG_PATH = Path(__file__).resolve().parent / "agent_plans.log"
_TOOLS_LOG_PATH = Path(__file__).resolve().parent / "agent_tools.log"
_GAME_STATE_LOG_PATH = Path(__file__).resolve().parent / "agent_game_state.log"
# Goals + per-line score modifiers are logged here, alongside the engine's
# candidate-line search payload (main.py writes the lines, agent.py writes the
# goal overlay that re-ranks them), so the strategy and its effect read together.
_SEARCH_LOG_PATH = Path(__file__).resolve().parent / "agent_search.log"
_LOG_INPUTS: bool = os.environ.get("RIFTBOUND_LOG_INPUTS", "0").strip() not in ("0", "", "false", "no")

# Maximum tool-call rounds before we give up and emit a decision
MAX_TOOL_ROUNDS = 6
# Model to use (can be overridden via RIFTBOUND_AI_MODEL env var)
DEFAULT_MODEL = "gpt-4o"


def _default_model() -> str:
    """Model used by the planner and actor stages."""
    return os.environ.get("RIFTBOUND_AI_MODEL", DEFAULT_MODEL)


def _strategist_model() -> str:
    """Model used by the per-turn goal strategist.

    Planning benefits most from a stronger (reasoning) model, and the strategist
    runs at most once per turn (cached), so its cost is amortized. Point ONLY the
    strategist at a bigger model with RIFTBOUND_STRATEGIST_MODEL without changing
    the planner/actor. Falls back to RIFTBOUND_AI_MODEL, then DEFAULT_MODEL.
    """
    return os.environ.get("RIFTBOUND_STRATEGIST_MODEL") or _default_model()


def _is_reasoning_model(model: str) -> bool:
    """True for OpenAI reasoning models (o-series, gpt-5) that emit a thinking
    stream before answering and reject the ``temperature`` sampling param.

    Used so the strategist can call such models cleanly (omit temperature) and
    default to the think/format split, which plays to their strength instead of
    fighting the single-call "JSON only" contract.
    """
    m = (model or "").strip().lower()
    return m.startswith(("o1", "o3", "o4", "gpt-5"))

_client: Optional[AsyncOpenAI] = None
_planner = planner_module.Planner()
_strategist = strategist_module.Strategist()

PIPELINE_LEGACY = "legacy"
PIPELINE_STAGED = "staged"


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        # Explicit timeout + bounded retries so a slow/unreachable API fails
        # fast instead of hanging on the SDK default (600s), which would block
        # the decision long after Godot has already timed out client-side.
        # The SDK retries transient failures (429/5xx/timeout) with backoff that
        # respects Retry-After; we also retry in-loop (see _chat_create) so a
        # brief rate limit does not collapse the whole decision into a pass.
        timeout = 30.0
        max_retries = int(os.environ.get("RIFTBOUND_CLIENT_MAX_RETRIES", "2"))
        provider = os.environ.get("RIFTBOUND_LLM_PROVIDER", "openai").strip().lower()
        if provider == "azure":
            # Azure AI Foundry exposes an OpenAI-compatible endpoint at
            # ``<resource>/openai/v1``. We use the plain OpenAI client pointed at
            # that base_url (NOT AzureOpenAI, which appends ?api-version=… and is
            # rejected by the v1 API). The "model" passed to the API is the Azure
            # *deployment* name, so name your deployment to match
            # RIFTBOUND_AI_MODEL (or set that var to the deployment name).
            endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
            if not endpoint:
                raise RuntimeError(
                    "RIFTBOUND_LLM_PROVIDER=azure requires AZURE_OPENAI_ENDPOINT "
                    "(your Azure Foundry project endpoint)."
                )
            base_url = endpoint.rstrip("/")
            # Accept either the bare resource endpoint or the full v1 base URL;
            # normalize so the caller can paste either from the portal.
            if not base_url.endswith("/openai/v1"):
                base_url = base_url.removesuffix("/openai") + "/openai/v1"
            _client = AsyncOpenAI(
                base_url=base_url,
                api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
                timeout=timeout,
                max_retries=max_retries,
            )
        else:
            _client = AsyncOpenAI(
                api_key=os.environ.get("OPENAI_API_KEY"),
                timeout=timeout,
                max_retries=max_retries,
            )
    return _client


def _record_token_usage(metrics: Optional[dict], stage: str, response: Any) -> None:
    """Accumulate token usage from one chat completion into ``metrics``.

    Tracks both overall totals and per-stage (``planner`` / ``actor``) totals so
    the planner and decision agents can be reported separately. Also bumps the
    per-stage model-call counter. Tolerates responses without a ``usage`` field
    (e.g. test doubles) by recording nothing.
    """
    if metrics is None:
        return
    usage = getattr(response, "usage", None)
    metrics[f"{stage}_model_calls"] = metrics.get(f"{stage}_model_calls", 0) + 1
    if usage is None:
        return
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    total = int(getattr(usage, "total_tokens", 0) or (prompt + completion))
    for key, value in (
        ("prompt_tokens", prompt),
        ("completion_tokens", completion),
        ("total_tokens", total),
        (f"{stage}_prompt_tokens", prompt),
        (f"{stage}_completion_tokens", completion),
        (f"{stage}_total_tokens", total),
    ):
        metrics[key] = metrics.get(key, 0) + value


async def _chat_create(
    client: AsyncOpenAI,
    *,
    metrics: Optional[dict] = None,
    stage: str = "actor",
    **kwargs,
):
    """Call chat.completions.create, retrying transient failures with backoff.

    The OpenAI SDK already retries internally up to ``max_retries``; this adds a
    second, in-process layer so a sustained-but-brief rate limit (429) is waited
    out rather than instantly degrading the decision to a fallback ``pass``. Only
    transient errors are retried; everything else propagates to the caller.

    ``stage`` ("actor" or "planner") routes token-usage accounting into
    stage-specific metric keys so the two agents can be reported separately.
    """
    last_exc: Exception | None = None
    # Reasoning models (o-series, gpt-5) reject a non-default ``temperature``.
    # The call sites (line selector, actor, planner) hardcode one, so strip it
    # here — the single choke point they all pass through — when targeting such
    # a model. Under Azure the model is a deployment name, so this relies on the
    # deployment being named after the underlying model (e.g. ``gpt-5.4``).
    if _is_reasoning_model(str(kwargs.get("model", ""))):
        kwargs.pop("temperature", None)
    for attempt in range(MAX_TRANSIENT_RETRIES + 1):
        try:
            response = await client.chat.completions.create(**kwargs)
            _record_token_usage(metrics, stage, response)
            return response
        except TRANSIENT_API_ERRORS as exc:
            last_exc = exc
            if metrics is not None:
                metrics["transient_retries"] = metrics.get("transient_retries", 0) + 1
            if attempt >= MAX_TRANSIENT_RETRIES:
                break
            delay = _transient_retry_delay(exc, attempt)
            logger.warning(
                "Transient API error (%s); retry %d/%d after %.1fs",
                type(exc).__name__, attempt + 1, MAX_TRANSIENT_RETRIES, delay,
            )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc


def _transient_retry_delay(exc: Exception, attempt: int) -> float:
    """Backoff seconds for a transient retry, honoring Retry-After when present."""
    retry_after = getattr(getattr(exc, "response", None), "headers", None)
    if retry_after:
        value = retry_after.get("retry-after")
        if value:
            try:
                return min(float(value), 10.0)
            except (TypeError, ValueError):
                pass
    return TRANSIENT_BACKOFF_BASE_S * (2 ** attempt)


# ── Tool definitions (OpenAI tool-call format) ────────────────────────────────

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_legal_moves",
            "description": (
                "Return the current enumerated list of legal command strings for "
                "this decision point. Call this when you want a concrete option set "
                "to reason over. The brief state already includes one, but this is "
                "always fresh."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_full_state",
            "description": (
                "Return the full board description for this seat. Useful when the "
                "brief state summary is not enough detail."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_zone",
            "description": (
                "Return a focused description of one zone. "
                "zone_id choices: 'my_hand', 'my_base_units', 'opponent_base_units', "
                "'my_runes', 'battlefield-a', 'battlefield-b'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "zone_id": {"type": "string", "description": "The zone to inspect."}
                },
                "required": ["zone_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_card_detail",
            "description": (
                "Return the full card definition (text, stats, keywords, abilities) "
                "for a card by its instance_id or base card id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "card_id": {"type": "string", "description": "The card instance_id or base id."}
                },
                "required": ["card_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_opponent_history",
            "description": "Return a summary of what the opponent has done this game.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_rule",
            "description": (
                "Search the Riftbound implementation rules for a topic or keyword. "
                "Call this when uncertain about a rules interaction rather than guessing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic, keyword, or rules question."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_keyword",
            "description": (
                "Return the precise glossary definition for a single keyword "
                "(e.g. Tank, Assault, Stun, Accelerate, Hidden). Cheaper and more "
                "exact than lookup_rule for one keyword."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The keyword name."}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_move",
            "description": (
                "Return the ENGINE-TRUTH result of a single move as structured "
                "facts (computed by the rules engine on a clone, not guessed). "
                "Use before asserting what a move does. The result separates "
                "'resolved_if_unanswered' (the deterministic outcome if the "
                "opponent does not respond — you may state these as fact) from "
                "'response_window' (a point the opponent could answer — you must "
                "hedge that branch). If 'error' is present, the move was not "
                "simulated; do not assert its outcome."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "move": {
                        "type": "object",
                        "description": "A move object with 'action' and 'parameters' fields.",
                        "properties": {
                            "action": {"type": "string"},
                            "parameters": {"type": "object"},
                        },
                        "required": ["action"],
                    }
                },
                "required": ["move"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_line",
            "description": (
                "Return the ENGINE-TRUTH result of a scripted multi-step line of "
                "YOUR OWN moves (e.g. move a unit into combat, THEN play a trick "
                "to win it). Pass the moves in order. 'resolved_if_unanswered' is "
                "the deterministic outcome assuming the opponent does not respond; "
                "each entry in 'opponent_windows' is a point the opponent could "
                "have answered — hedge those. Use this for combat/contested lines "
                "instead of guessing how the sequence resolves."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "moves": {
                        "type": "array",
                        "description": "Ordered list of move objects, each with 'action' and 'parameters'.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string"},
                                "parameters": {"type": "object"},
                            },
                            "required": ["action"],
                        },
                    }
                },
                "required": ["moves"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_position",
            "description": (
                "Return a heuristic assessment of the current board position: "
                "score advantage, unit counts, battlefield control, and overall outlook."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_turn",
            "description": (
                "Return the engine's top candidate full-turn lines for THIS turn "
                "(a cheap scout search the engine ran up front). Each line is a "
                "sequence the rules engine actually simulated, with its mechanical "
                "score and the top scoring terms driving it. Call this FIRST when "
                "setting goals: see what the search can already achieve, then set "
                "goals that sharpen the best line or redirect the search toward a "
                "winning idea it is missing. Empty if no scout search ran."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "top_n": {
                        "type": "integer",
                        "description": "How many top lines to return (default 5).",
                    }
                },
                "required": [],
            },
        },
    },
]


# ── Skill dispatch ────────────────────────────────────────────────────────────


def _dispatch_tool(name: str, arguments: dict) -> Any:
    if name == "list_legal_moves":
        return skill_module.list_legal_moves()
    if name == "get_full_state":
        return skill_module.get_full_state()
    if name == "get_zone":
        return skill_module.get_zone(arguments.get("zone_id", ""))
    if name == "get_card_detail":
        return skill_module.get_card_detail(arguments.get("card_id", ""))
    if name == "get_opponent_history":
        return skill_module.get_opponent_history()
    if name == "lookup_rule":
        return skill_module.lookup_rule(arguments.get("query", ""))
    if name == "get_keyword":
        return skill_module.get_keyword(arguments.get("name", ""))
    if name == "simulate_move":
        return skill_module.simulate_move(arguments.get("move", {}))
    if name == "simulate_line":
        return skill_module.simulate_line(arguments.get("moves", []))
    if name == "evaluate_position":
        return skill_module.evaluate_position()
    if name == "search_turn":
        return skill_module.search_turn(arguments.get("top_n", 5))
    return f"Unknown skill: {name}"


# ── Decision parsing ──────────────────────────────────────────────────────────


def _parse_decision(content: str) -> Optional[Decision]:
    """Try to parse the model's text response as a Decision JSON object."""
    content = content.strip()
    # Strip markdown fences if present
    if content.startswith("```"):
        content = "\n".join(
            line for line in content.splitlines()
            if not line.strip().startswith("```")
        ).strip()
    try:
        data = json.loads(content)
        return Decision.model_validate(data)
    except Exception as exc:
        logger.warning("Decision parse failed: %s", exc)
        return None


def _parse_line_choice(content: str) -> dict | None:
    content = content.strip()
    if content.startswith("```"):
        content = "\n".join(
            line for line in content.splitlines()
            if not line.strip().startswith("```")
        ).strip()
    try:
        data = json.loads(content)
        if isinstance(data, dict) and data.get("chosen_line_id"):
            return data
    except Exception as exc:
        logger.warning("Line choice parse failed: %s", exc)
    return None


# Modifier keywords that introduce a parameter (or flag) inside a command.
# Everything before the first one of these is the command "head" (verb + ids).
_CMD_KEYWORDS = frozenset({"to", "target", "at", "from", "accelerate"})


def _parse_command(cmd: str) -> Optional[dict]:
    """Parse a console command into a normalized structure for comparison.

    Returns a dict with the verb, the identifying head tokens (card / unit ids),
    and any optional modifiers (destination, target, at, flags). Returns None
    when the command contains a token we don't know how to validate, so the
    caller can fall back to rejecting it.
    """
    tokens = cmd.split()
    if not tokens:
        return None

    parsed: dict[str, Any] = {
        "verb": tokens[0],
        "head": [],
        "to": None,
        "target": None,
        "at": None,
        "flags": set(),
    }

    rest = tokens[1:]
    i = 0
    # Head tokens run until the first modifier keyword.
    while i < len(rest) and rest[i] not in _CMD_KEYWORDS:
        parsed["head"].append(rest[i])
        i += 1

    while i < len(rest):
        tok = rest[i]
        if tok in ("to", "target", "at") and i + 1 < len(rest):
            parsed[tok] = rest[i + 1]
            i += 2
        elif tok == "from" and i + 1 < len(rest):
            parsed["flags"].add(f"from {rest[i + 1]}")
            i += 2
        elif tok == "accelerate":
            parsed["flags"].add("accelerate")
            i += 1
        else:
            # Dangling keyword or unrecognized token — not safely validatable.
            return None

    parsed["head"] = tuple(parsed["head"])
    return parsed


def _norm_dest(dest: Optional[str]) -> Optional[str]:
    """Treat an omitted destination and an explicit 'base' as equivalent.

    The enumerator emits ``play <id>`` (no destination) for cards going to base,
    while the model may emit ``play <id> to base``; both mean the same thing.
    """
    return None if dest == "base" else dest


def _visible_instance_ids(brief_state: Optional[dict]) -> set[str]:
    """Collect every instance_id the seat can see, for validating target params."""
    ids: set[str] = set()
    if not brief_state:
        return ids

    def _add(entries: Any) -> None:
        for e in entries or []:
            iid = e.get("instance_id") if isinstance(e, dict) else None
            if iid:
                ids.add(iid)

    _add(brief_state.get("my_hand"))
    _add(brief_state.get("my_base_units"))
    _add(brief_state.get("opponent_base_units"))
    champ = brief_state.get("my_champion")
    if isinstance(champ, dict) and champ.get("instance_id"):
        ids.add(champ["instance_id"])
    for bf in brief_state.get("battlefields", []) or []:
        _add(bf.get("my_units"))
        _add(bf.get("opponent_units"))
        fd = bf.get("my_facedown")
        if isinstance(fd, dict) and fd.get("instance_id"):
            ids.add(fd["instance_id"])
    return ids


def _matches_legal_move(cand: dict, legal: dict, valid_target_ids: set[str]) -> bool:
    """True if a candidate command is permitted by an enumerated legal move.

    Matches token-by-token rather than as an opaque string: the verb, ids,
    destination, location, and flags must agree, and a target may be added on
    top of a base (untargeted) legal move as long as it names a visible
    instance. This lets targeted spells/reactions — whose enumerated form is the
    bare ``play <id>`` / ``react <id>`` (target chosen via a follow-up prompt) —
    pass with an inline ``target <id>`` too, since the engine accepts both.
    """
    if cand["verb"] != legal["verb"]:
        return False
    if cand["head"] != legal["head"]:
        return False
    if _norm_dest(cand["to"]) != _norm_dest(legal["to"]):
        return False
    if cand["at"] != legal["at"]:
        return False
    if cand["flags"] != legal["flags"]:
        return False

    if cand["target"] == legal["target"]:
        return True
    # The enumerated move carries no target but the candidate adds one: accept
    # it when it references a real, visible instance (the engine validates the
    # precise target legality itself on submit).
    if legal["target"] is None and cand["target"] is not None:
        return (not valid_target_ids) or (cand["target"] in valid_target_ids)
    return False


def _command_in_legal_moves(
    cmd: str, legal: list, brief_state: Optional[dict] = None
) -> bool:
    """Return True if cmd is permitted, validating each token/param.

    Falls back from an exact string match to a structured, per-parameter
    comparison so that legitimate variations (e.g. ``play <id> to base`` for a
    base play, or ``play <id> target <id>`` for a targeted spell) are accepted
    even though only the canonical form is enumerated.
    """
    if cmd in legal:
        return True

    cand = _parse_command(cmd)
    if cand is None:
        return False

    valid_target_ids = _visible_instance_ids(brief_state)
    for lm in legal:
        parsed_lm = _parse_command(lm)
        if parsed_lm is None:
            continue
        if _matches_legal_move(cand, parsed_lm, valid_target_ids):
            return True
    return False


_PASS_DECISION = Decision(
    reasoning="Fallback: could not produce a valid decision within retry budget.",
    move=Move(action="pass"),
)


def _log_input(game_id: str, brief_state: dict, messages: list) -> None:
    """Write a snapshot of the full agent input to agent_inputs.log."""
    if not _LOG_INPUTS:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sep = "─" * 72
    lines = [
        "",
        sep,
        f"Turn {brief_state.get('turn_number', '?')}  "
        f"Type: {brief_state.get('decision_type', '?')}  "
        f"Game: {game_id}  [{ts}]",
        sep,
    ]
    for msg in messages:
        role = msg.get("role", "?").upper()
        content = msg.get("content") or ""
        if content:
            lines.append(f"[{role}]")
            lines.append(content)
            lines.append("")
    try:
        with _INPUT_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as exc:
        logger.warning("Input log write failed: %s", exc)


def _log_plan(
    game_id: str,
    brief_state: dict,
    plan: "Plan",
    *,
    was_cached: bool,
    decision_index: Optional[int] = None,
) -> None:
    """Write the turn plan used for this decision to agent_plans.log.

    One entry per decision that consults a plan, annotated with the turn,
    decision type, decision index, and whether the plan was freshly generated
    or reused from the per-turn cache.
    """
    if not _LOG_INPUTS:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sep = "─" * 72
    origin = "CACHED (reused this turn)" if was_cached else "FRESH (new planner call)"
    lines = [
        "",
        sep,
        f"Turn {brief_state.get('turn_number', '?')}  "
        f"Type: {brief_state.get('decision_type', '?')}  "
        f"Decision #: {decision_index if decision_index is not None else '?'}  "
        f"Game: {game_id}  [{ts}]",
        f"Plan source: {origin}",
        sep,
        plan.model_dump_json(indent=2),
        "",
    ]
    try:
        with _PLAN_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as exc:
        logger.warning("Plan log write failed: %s", exc)


def _log_tools(
    game_id: str,
    brief_state: dict,
    *,
    tool_trace: list[dict],
    outcome: str,
    stage: str = "actor",
) -> None:
    """Write the tool calls made while resolving one decision to agent_tools.log.

    One entry per decision, keyed by turn / decision_type / current_state, listing
    every tool the model called (round, name, args) and the terminal outcome
    (the action chosen, or why it fell back to pass). This makes it possible to
    see whether a fallback was caused by tool churn or by validator rejection.
    """
    if not _LOG_INPUTS:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sep = "─" * 72
    lines = [
        "",
        sep,
        f"Turn {brief_state.get('turn_number', '?')}  "
        f"Type: {brief_state.get('decision_type', '?')}  "
        f"State: {brief_state.get('current_state', '?')}  "
        f"Stage: {stage}  "
        f"Game: {game_id}  [{ts}]",
        sep,
        f"Tool calls: {len(tool_trace)}",
    ]
    if tool_trace:
        for entry in tool_trace:
            args = entry.get("args", {})
            args_str = json.dumps(args, default=str) if args else "{}"
            lines.append(
                f"  round {entry.get('round', '?')}: "
                f"{entry.get('name', '?')}({args_str})"
            )
    else:
        lines.append("  (none — model answered without consulting any tool)")
    lines.append(f"Outcome: {outcome}")
    lines.append("")
    try:
        with _TOOLS_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as exc:
        logger.warning("Tools log write failed: %s", exc)


def _log_game_state_event(
    *,
    game_id: str,
    turn: int,
    event_type: str,
    description: str,
    actor: Optional[str] = None,
    command: Optional[str] = None,
    decision_type: Optional[str] = None,
    state: Optional[dict] = None,
) -> None:
    """Write a game timeline event and optional post-event state snapshot."""
    if not _LOG_INPUTS:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sep = "-" * 72
    actor_part = f"  Actor: {actor}" if actor else ""
    lines = [
        "",
        sep,
        f"Turn {turn}  Event: {event_type}{actor_part}  Game: {game_id}  [{ts}]",
        sep,
        f"Description: {description}",
    ]
    if decision_type:
        lines.append(f"Decision type: {decision_type}")
    if command:
        lines.append(f"Command: {command}")
    if state:
        lines.append("")
        lines.append("State after event:")
        lines.append(_format_brief_state(state))
    lines.append("")
    try:
        with _GAME_STATE_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as exc:
        logger.warning("Game state log write failed: %s", exc)


# ── Main reasoning loop ───────────────────────────────────────────────────────


async def decide(
    brief_state: dict,
    game_id: str,
    memory: Memory,
    rejection_context: Optional[dict] = None,
    eval_metrics: Optional[dict] = None,
    pipeline_mode: Optional[str] = None,
) -> Decision:
    _start_ts = time.monotonic()
    metrics = eval_metrics if eval_metrics is not None else {}
    metrics.update({
        "model_calls": 0,
        "tool_rounds": 0,
        "parse_retries": 0,
        "legality_retries": 0,
        "transient_retries": 0,
        "fell_back_to_pass": False,
        "latency_ms": 0,
        # Token usage (overall + per-stage planner/actor breakdown). Populated by
        # _chat_create via _record_token_usage as model calls are made.
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "planner_model_calls": 0,
        "planner_prompt_tokens": 0,
        "planner_completion_tokens": 0,
        "planner_total_tokens": 0,
        "actor_model_calls": 0,
        "actor_prompt_tokens": 0,
        "actor_completion_tokens": 0,
        "actor_total_tokens": 0,
    })

    def _finalize(decision: Decision, fell_back: bool) -> Decision:
        metrics["fell_back_to_pass"] = fell_back
        metrics["latency_ms"] = int((time.monotonic() - _start_ts) * 1000)
        return decision

    requested_pipeline = (pipeline_mode or os.environ.get("RIFTBOUND_PIPELINE", PIPELINE_LEGACY)).strip().lower()
    selected_pipeline = requested_pipeline if requested_pipeline in (PIPELINE_LEGACY, PIPELINE_STAGED) else PIPELINE_LEGACY

    if selected_pipeline == PIPELINE_STAGED:
        decision = await _decide_staged(
            brief_state=brief_state,
            game_id=game_id,
            memory=memory,
            rejection_context=rejection_context,
            metrics=metrics,
        )
    else:
        decision = await _decide_legacy(
            brief_state=brief_state,
            game_id=game_id,
            memory=memory,
            rejection_context=rejection_context,
            metrics=metrics,
        )
    return _finalize(decision, fell_back=(decision == _PASS_DECISION))


def _format_rejection_context(rejection_context: Optional[dict]) -> str:
    if not rejection_context:
        return ""
    return (
        f"\n\n## Previous Move Was Rejected\n"
        f"Rejected move: {json.dumps(rejection_context.get('rejected_move', {}))}\n"
        f"Reason: {rejection_context.get('rejection_reason', 'unknown')}\n"
        f"In one sentence, state what you misunderstood or assumed incorrectly. "
        f"Then produce a corrected move."
    )


def _legality_failure_reason(decision: Decision, brief_state: dict) -> str | None:
    cmd = decision.move.to_command()
    legal = brief_state.get("legal_moves", [])
    if legal and not _command_in_legal_moves(cmd, legal, brief_state):
        return (
            f"Your move translates to '{cmd}', which is NOT in the current legal_moves list. "
            f"You must pick exactly one command that appears in legal_moves "
            f"(omit destination for units played to base — use play_card without destination, not 'to base'). "
            f"For hiding a Hidden card from hand, use hide_card — not play_card with from_hidden. "
            f"Respond with corrected JSON."
        )
    return None


def _plan_consistency_failure_reason(
    *,
    decision: Decision,
    brief_state: dict,
    plan: Plan | None,
    strict_plan_check: bool,
) -> str | None:
    if not strict_plan_check or plan is None:
        return None
    if plan.tactical_flexibility == "high":
        return None

    cmd = decision.move.to_command()
    parsed = _parse_command(cmd)
    if parsed is None:
        return None

    battlefield_targets = set(plan.focus_battlefields)
    if plan.target_profile.kind == "battlefield":
        battlefield_targets.update(plan.target_profile.ids)

    move_location = parsed.get("to") or parsed.get("at")
    if battlefield_targets and move_location and move_location.startswith("battlefield-"):
        if move_location not in battlefield_targets:
            return (
                f"Plan intent is '{plan.intent}' and focuses on {sorted(battlefield_targets)}, "
                f"but your move commits to '{move_location}'. Choose a move aligned with the plan."
            )

    explicit_targets = set(plan.target_profile.ids)
    if plan.target_profile.kind in ("unit", "card", "player") and explicit_targets:
        chosen_target = parsed.get("target")
        if chosen_target and chosen_target not in explicit_targets:
            return (
                f"Plan target profile expects one of {sorted(explicit_targets)}, but move targets "
                f"'{chosen_target}'. Choose a move aligned with the plan."
            )

    if decision.confidence is not None and str(decision.confidence).strip().lower() == "low":
        return "Confidence is too low for this strategic decision. Choose a clearer plan-aligned move."

    return None


def _move_from_command(cmd: str) -> Move | None:
    parsed = _parse_command(cmd)
    if parsed is None:
        return None
    head = list(parsed["head"])
    target = parsed["target"] or ""
    to = parsed["to"] or ""
    at = parsed["at"] or ""
    flags = parsed["flags"]
    verb = parsed["verb"]

    if cmd == "end turn":
        return Move(action="end_turn")
    if cmd == "pass":
        return Move(action="pass")
    if cmd == "assign done":
        return Move(action="assign_done")
    if cmd == "choose none":
        return Move(action="choose_none")
    if verb == "mulligan":
        if head and head[0] == "keep":
            return Move(action="mulligan_keep")
        return Move(action="mulligan", parameters={"card_ids": head})
    if verb == "play" and head:
        params: dict[str, Any] = {"card_id": head[0]}
        if to:
            params["destination"] = to
        if target:
            params["target_id"] = target
        params["from_champion"] = "from champion" in flags
        params["from_hidden"] = "from hidden" in flags
        params["accelerate"] = "accelerate" in flags
        return Move(action="play_card", parameters=params)
    if verb == "hide" and head and at:
        return Move(action="hide_card", parameters={"card_id": head[0], "battlefield_id": at})
    if verb == "move" and head and to:
        return Move(action="move_unit", parameters={"unit_ids": head, "destination": to})
    if verb == "use" and head:
        params = {"card_id": head[0]}
        if target:
            params["target_id"] = target
        return Move(action="use_ability", parameters=params)
    if verb == "react" and head:
        params = {"card_id": head[0]}
        if target:
            params["target_id"] = target
        return Move(action="react", parameters=params)
    if verb == "assign" and len(head) == 1 and target:
        try:
            amount = int(head[0])
        except ValueError:
            return None
        return Move(action="assign_damage", parameters={"amount": amount, "target_id": target})
    if verb == "choose" and head:
        return Move(action="choose", parameters={"target_id": head[0]})
    return None


def _line_move_command(move: Any) -> str:
    if isinstance(move, str):
        return move
    if isinstance(move, Move):
        return move.to_command()
    if isinstance(move, dict):
        try:
            return Move.model_validate(move).to_command()
        except Exception:
            return str(move)
    return str(move)


def _render_line_steps(line: CandidateLine) -> list[dict]:
    """Render each step of a line as {command, context, kind} so the model can
    see WHY intermediate steps exist (e.g. 'pass showdown focus', 'choose target
    X for ability Y') rather than just an opaque command string."""
    commands = [_line_move_command(m) for m in line.moves]
    out: list[dict] = []
    for i, cmd in enumerate(commands):
        ctx = line.move_contexts[i] if i < len(line.move_contexts) else {}
        step: dict[str, Any] = {"command": cmd, "kind": ctx.get("kind", "scripted")}
        context_text = ctx.get("context", "")
        if context_text:
            step["context"] = context_text
        out.append(step)
    return out


def _line_move_strings(line: CandidateLine) -> list[str]:
    return [_line_move_command(m) for m in line.moves]


def _summarize_lines_for_strategist(
    lines: list[CandidateLine], *, top_n: int = 5, top_terms: int = 4
) -> list[dict]:
    """Compact the engine's candidate lines into what the strategist needs.

    The full CandidateLine carries heavy fields (full features, resolved_state) the
    strategist does not need to set goals. This keeps only the decision-relevant
    shape: the move sequence, the mechanical score, the few score terms driving it,
    and whether the opponent gets a response window (a line the strategist should
    treat as contestable). Sorted best-first so top_n is meaningful.
    """
    ordered = sorted(lines, key=lambda ln: float(ln.score), reverse=True)
    out: list[dict] = []
    for line in ordered[: max(1, int(top_n))]:
        breakdown = line.score_breakdown or {}
        drivers = sorted(
            ((k, float(v)) for k, v in breakdown.items() if isinstance(v, (int, float))),
            key=lambda kv: abs(kv[1]),
            reverse=True,
        )[:top_terms]
        out.append({
            "line_id": line.line_id,
            "moves": _line_move_strings(line),
            "score": round(float(line.score), 3),
            "top_score_terms": {k: round(v, 3) for k, v in drivers},
            "contested": bool(line.opponent_windows),
            "opponent_windows": len(line.opponent_windows),
        })
    return out


def _adjusted_line_score(line: CandidateLine, overlay: ProfileOverlay) -> float:
    """Engine score plus the goal overlay's bias for this line (re-rank)."""
    return float(line.score) + overlay_delta(
        overlay,
        features=line.features or {},
        score_breakdown=line.score_breakdown or {},
        moves=_line_move_strings(line),
    )


def _goal_selector_context(overlay: Optional[ProfileOverlay]) -> str:
    """One-line goal briefing injected into the line-selector system prompt."""
    if overlay is None or overlay.is_empty():
        return ""
    bits: list[str] = []
    for key, mult in overlay.weight_multipliers.items():
        bits.append(f"lean {key.split('.', 1)[-1]} ×{mult:.2f}")
    for term in overlay.situational_terms:
        tgt = f"{term['metric']}[{term['metric_key']}]" if term.get("metric_key") else term["metric"]
        bits.append(f"reach {tgt} {term['comparator']} {term['threshold']}")
    for bonus in overlay.card_bonuses:
        bits.append(f"play {bonus['card_id']}")
    goals = "; ".join(bits)
    return (
        "This turn's GOALS bias the score — prefer the line with the best "
        f"'goal_adjusted_score' unless an opponent window makes it unsafe. Goals: {goals}. "
    )


async def build_goal_overlay(
    *,
    brief_state: dict,
    game_id: str,
    memory: Memory,
    eval_metrics: Optional[dict] = None,
    candidate_lines: Optional[list[CandidateLine]] = None,
    search_stats: Optional[SearchStats] = None,
) -> ProfileOverlay:
    """Run the per-turn strategist and compile its GoalSet into an overlay.

    Cached once per turn by the Strategist (invalidated when the opponent acts),
    so the LLM cost is paid at most once per turn. Any failure degrades to an
    empty overlay (today's base-profile selection), never an exception.

    When ``candidate_lines`` are supplied (Phase 1 scout search), they are
    summarized and installed so the strategist's ``search_turn`` tool grounds its
    goals in the engine's actual best lines instead of a static snapshot.
    """
    opponent_action_count = memory.count_opponent_material_actions(game_id)
    timeline = memory.timeline_slice(game_id)
    scout_summaries = (
        _summarize_lines_for_strategist(candidate_lines) if candidate_lines else []
    )
    skill_module.set_search_context(
        scout_summaries,
        search_stats.model_dump() if search_stats else {},
    )
    try:
        goal_set, was_cached = await _strategist.goals(
            client=get_client(),
            model=_strategist_model(),
            game_id=game_id,
            brief_state=brief_state,
            memory_summary=timeline,
            opponent_action_count=opponent_action_count,
            metrics=eval_metrics,
            has_scout_lines=bool(scout_summaries),
        )
    finally:
        # Clear so a later decision in the same turn (or a turn with no scout)
        # never serves stale lines through search_turn.
        skill_module.set_search_context(None)
    overlay = compile_goals(goal_set)
    if not was_cached:
        _log_goals(game_id, brief_state, goal_set, overlay)
    return overlay


def _log_goals(game_id: str, brief_state: dict, goal_set: "GoalSet", overlay: ProfileOverlay) -> None:
    """Append the turn's GoalSet + compiled overlay to the plan log (when input
    logging is on). Mirrors _log_plan's gating; goal-specific so it shares the log
    with the planner without colliding on the Plan schema."""
    if not _LOG_INPUTS:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sep = "─" * 72
    lines = [
        "",
        sep,
        f"Turn {brief_state.get('turn_number', '?')}  "
        f"Type: {brief_state.get('decision_type', '?')}  Game: {game_id}  [{ts}]",
        f"GoalSet goals={len(goal_set.goals)}: {goal_set.rationale}",
    ]
    for g in goal_set.goals:
        lines.append(f"  - [{g.kind}] {g.id} ({g.priority}) {g.description}".rstrip())
    lines.append("Compiled overlay:")
    lines.extend(f"  · {note}" for note in overlay.notes)
    lines.append("")
    try:
        with _SEARCH_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as exc:
        logger.warning("Goal log write failed: %s", exc)


def _log_overlay_scores(
    game_id: str,
    brief_state: dict,
    candidate_lines: list[CandidateLine],
    overlay: ProfileOverlay,
    *,
    chosen_id: str | None,
) -> None:
    """Append the goal score modifier per candidate line to the plan log.

    For each line: base engine score, overlay delta, adjusted score, and the
    per-goal contributions that make up the delta. Lets you see exactly how the
    goals re-ranked the lines and which line won. Gated on input logging like the
    other goal logs; no-op when the overlay is empty."""
    if not _LOG_INPUTS or overlay is None or overlay.is_empty():
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sep = "─" * 72
    lines = [
        "",
        sep,
        f"Turn {brief_state.get('turn_number', '?')}  Goal score modifiers  "
        f"Game: {game_id}  [{ts}]",
        sep,
    ]
    rows = []
    for line in candidate_lines:
        parts = overlay_delta_breakdown(
            overlay,
            features=line.features or {},
            score_breakdown=line.score_breakdown or {},
            moves=_line_move_strings(line),
        )
        delta = sum(parts.values())
        rows.append((float(line.score) + delta, line.line_id, float(line.score), delta, parts))
    rows.sort(key=lambda r: r[0], reverse=True)
    for adj, lid, base, delta, parts in rows:
        mark = " ◄ chosen" if lid == chosen_id else ""
        detail = ", ".join(f"{k}{v:+.2f}" for k, v in parts.items()) if parts else "—"
        lines.append(f"  {lid}: base={base:.2f} {delta:+.2f} → {adj:.2f}  [{detail}]{mark}")
    lines.append("")
    try:
        with _SEARCH_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as exc:
        logger.warning("Overlay score log write failed: %s", exc)


async def choose_line(
    *,
    brief_state: dict,
    game_id: str,
    memory: Memory,
    candidate_lines: list[CandidateLine],
    search_stats: SearchStats | None = None,
    eval_metrics: Optional[dict] = None,
    argmax_only: bool = False,
    overlay: Optional["ProfileOverlay"] = None,
) -> Decision:
    """Use the Actor as a compact policy selector over Godot-searched lines.

    When ``argmax_only`` is set (RIFTBOUND_SEARCH_ARGMAX), the LLM round-trip is
    skipped entirely and the top-scored playable line is returned directly. This
    is the bulk data-generation / weight-tuning regime; rows are tagged
    ``selector_source='argmax'`` so the two regimes stay separable.

    When a goal ``overlay`` is supplied (goal-oriented strategist), each line's
    engine score is biased by ``overlay_delta`` before ranking, so the selection
    optimizes the turn's goals. The base profile / search are untouched; this is
    the server-side re-rank path (a line the search never generated still cannot
    be chosen — that gap is closed by the engine-side overlay).
    """
    if not candidate_lines:
        return _PASS_DECISION
    if argmax_only:
        decision = _argmax_line(candidate_lines, source="argmax", overlay=overlay)
        _log_overlay_scores(game_id, brief_state, candidate_lines, overlay, chosen_id=decision.chosen_line_id)
        return decision
    # Single forced line: nothing to choose, so skip the LLM selector entirely
    # (mirrors the router's single-legal-move short-circuit for the search path).
    single = _single_playable_line(candidate_lines)
    if single is not None:
        _log_overlay_scores(game_id, brief_state, candidate_lines, overlay, chosen_id=single.chosen_line_id)
        return single
    metrics = eval_metrics if eval_metrics is not None else {}
    metrics.setdefault("model_calls", 0)
    metrics.setdefault("actor_model_calls", 0)
    skill_module.set_history_context(memory, game_id)
    legal_ids = {line.line_id for line in candidate_lines}
    lines_payload = []
    for line in candidate_lines:
        entry = {
            "line_id": line.line_id,
            "steps": _render_line_steps(line),
            "score": line.score,
            "score_breakdown": line.score_breakdown,
            "resolved_state": line.resolved_state,
            "opponent_windows": [w.model_dump() for w in line.opponent_windows],
        }
        if overlay is not None and not overlay.is_empty():
            entry["goal_adjusted_score"] = _adjusted_line_score(line, overlay)
        lines_payload.append(entry)
    goal_context = _goal_selector_context(overlay)
    messages: list[ChatCompletionMessageParam] = [
        {
            "role": "system",
            "content": (
                "You choose one full-turn line from Godot's engine search. "
                "Each line is a list of ordered steps. A step's kind is "
                "'scripted' (a deliberate play) or 'intermediate' (a forced "
                "sub-decision the engine auto-resolves mid-line, e.g. passing "
                "showdown focus or choosing an ability target — its 'context' "
                "explains it). The engine score is mechanical; use "
                "opponent-history judgement for contested opponent_windows. "
                f"{goal_context}"
                "You may call get_opponent_history. "
                "Respond with raw JSON only: {\"chosen_line_id\":\"line-1\","
                "\"reasoning\":\"...\"}."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "turn": brief_state.get("turn_number"),
                    "decision_type": brief_state.get("decision_type"),
                    "my_score": brief_state.get("my_score"),
                    "opponent_score": brief_state.get("opponent_score"),
                    "search_stats": search_stats.model_dump() if search_stats else {},
                    "candidate_lines": lines_payload,
                },
                indent=2,
            ),
        },
    ]
    _log_input(game_id, brief_state, messages)
    tools = [t for t in TOOLS if t.get("function", {}).get("name") == "get_opponent_history"]
    for round_num in range(3):
        try:
            response = await _chat_create(
                get_client(),
                metrics=metrics,
                model=os.environ.get("RIFTBOUND_AI_MODEL", DEFAULT_MODEL),
                messages=messages,
                tools=tools,  # type: ignore[arg-type]
                tool_choice="auto",  # type: ignore[arg-type]
                temperature=0.2,
                response_format={"type": "text"},
            )
            metrics["model_calls"] = metrics.get("model_calls", 0) + 1
        except Exception as exc:
            logger.error("Line selector API error: %s", exc)
            break
        msg = response.choices[0].message
        if msg.tool_calls:
            messages.append(msg)  # type: ignore[arg-type]
            for tc in msg.tool_calls:
                result = _dispatch_tool(tc.function.name, {})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            continue
        parsed = _parse_line_choice(msg.content or "")
        if parsed and parsed["chosen_line_id"] in legal_ids:
            chosen = next(line for line in candidate_lines if line.line_id == parsed["chosen_line_id"])
            commands = [_line_move_command(m) for m in chosen.moves]
            first_move = _move_from_command(commands[0]) if commands else None
            if first_move is not None:
                _log_overlay_scores(game_id, brief_state, candidate_lines, overlay, chosen_id=chosen.line_id)
                return Decision(
                    reasoning=str(parsed.get("reasoning", "Selected searched line.")),
                    move=first_move,
                    confidence="high",
                    alternatives_considered=f"Selected from {len(candidate_lines)} searched lines.",
                    chosen_line_id=chosen.line_id,
                    selector_source="llm",
                )
        messages.append({"role": "user", "content": "Choose a valid line_id from the provided candidate_lines and return raw JSON only."})
    # Fallback: pick the highest-scoring line that actually starts with a usable
    # move. A line with no parseable first move cannot be committed (Godot would
    # replay a move the search never planned), so such lines are skipped and we
    # pass without committing a line if none qualify.
    decision = _argmax_line(candidate_lines, source="fallback", overlay=overlay)
    _log_overlay_scores(game_id, brief_state, candidate_lines, overlay, chosen_id=decision.chosen_line_id)
    return decision


def _playable_lines(
    candidate_lines: list[CandidateLine],
) -> list[tuple[CandidateLine, Move]]:
    """Lines whose first move parses into a committable Move, paired with it.

    A line with no parseable first move cannot be committed (Godot would replay a
    move the search never planned), so it is excluded from selection everywhere.
    """
    playable: list[tuple[CandidateLine, Move]] = []
    for line in candidate_lines:
        commands = [_line_move_command(m) for m in line.moves]
        first_move = _move_from_command(commands[0]) if commands else None
        if first_move is not None:
            playable.append((line, first_move))
    return playable


def _single_playable_line(
    candidate_lines: list[CandidateLine],
) -> Decision | None:
    """If exactly one line is committable, return it as a forced Decision.

    There is nothing to choose among a single line, so both the strategist re-rank
    and the LLM selector round-trip are pointless — this mirrors the router's
    single-legal-move short-circuit for the search path. Returns None when 0 or ≥2
    lines are playable (the caller then runs the normal selector / argmax).
    """
    playable = _playable_lines(candidate_lines)
    if len(playable) != 1:
        return None
    line, move = playable[0]
    return Decision(
        reasoning="Only one playable line was available; committed it without deliberation.",
        move=move,
        confidence="high",
        alternatives_considered="No alternatives — a single line was available.",
        chosen_line_id=line.line_id,
        selector_source="single",
    )


def _argmax_line(
    candidate_lines: list[CandidateLine],
    *,
    source: str,
    overlay: Optional["ProfileOverlay"] = None,
) -> Decision:
    """Return the highest-scoring playable line as a Decision (engine argmax).

    Shared by the LLM-selector fallback (``source='fallback'``) and the no-LLM
    argmax data-generation path (``source='argmax'``). When a goal ``overlay`` is
    supplied, ranking uses the goal-adjusted score instead of the raw engine
    score.
    """
    playable = _playable_lines(candidate_lines)
    if not playable:
        return _PASS_DECISION
    use_overlay = overlay is not None and not overlay.is_empty()
    if use_overlay:
        best, best_move = max(playable, key=lambda pair: _adjusted_line_score(pair[0], overlay))
    else:
        best, best_move = max(playable, key=lambda pair: pair[0].score)
    if source == "argmax":
        reasoning = (
            "Goal-argmax: selected the highest goal-adjusted searched line."
            if use_overlay
            else "Argmax: selected the highest-scoring searched line."
        )
    else:
        reasoning = (
            "Goal-fallback: selected the highest goal-adjusted searched line."
            if use_overlay
            else "Fallback: selected the highest-scoring searched line."
        )
    return Decision(
        reasoning=reasoning,
        move=best_move,
        confidence="medium",
        alternatives_considered=f"Search selector {source} among {len(candidate_lines)} lines.",
        chosen_line_id=best.line_id,
        selector_source=source,
    )


def _forced_decision(cmd: str) -> Decision | None:
    move = _move_from_command(cmd)
    if move is None:
        return None
    return Decision(
        reasoning="Forced decision: only one legal move was available.",
        move=move,
        confidence="high",
    )


async def _run_actor_loop(
    *,
    model: str,
    brief_state: dict,
    game_id: str,
    messages: list[ChatCompletionMessageParam],
    metrics: dict,
    strict_plan_check: bool = False,
    plan: Plan | None = None,
    max_validator_retries: int = MAX_TOOL_ROUNDS,
) -> Decision:
    validator_retries = 0
    tool_trace: list[dict] = []

    def _finish(decision: Decision, outcome: str) -> Decision:
        _log_tools(
            game_id,
            brief_state,
            tool_trace=tool_trace,
            outcome=outcome,
        )
        return decision

    for round_num in range(MAX_TOOL_ROUNDS):
        # Force at least one grounding tool call on the first round so the model
        # consults state/rules before committing. The "only JSON" output contract
        # otherwise biases it to answer immediately without ever calling a tool.
        tool_choice = "required" if round_num == 0 else "auto"
        try:
            response = await _chat_create(
                get_client(),
                metrics=metrics,
                model=model,
                messages=messages,
                tools=TOOLS,  # type: ignore[arg-type]
                tool_choice=tool_choice,  # type: ignore[arg-type]
                temperature=0.3,
                response_format={"type": "text"},
            )
            metrics["model_calls"] += 1
        except TRANSIENT_API_ERRORS as exc:
            logger.error("OpenAI API rate-limited/unavailable after retries: %s", exc)
            return _finish(
                _PASS_DECISION,
                f"pass (transient API failure after retries: {type(exc).__name__})",
            )
        except Exception as exc:
            logger.error("OpenAI API error: %s", exc)
            return _finish(_PASS_DECISION, f"pass (OpenAI API error: {exc})")

        msg = response.choices[0].message
        if msg.tool_calls:
            metrics["tool_rounds"] += 1
            messages.append(msg)  # type: ignore[arg-type]
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                tool_trace.append(
                    {"round": round_num, "name": tc.function.name, "args": args}
                )
                result = _dispatch_tool(tc.function.name, args)
                result_text = json.dumps(result) if not isinstance(result, str) else result
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_text})
            continue

        content = msg.content or ""
        decision = _parse_decision(content)
        if decision is None:
            metrics["parse_retries"] += 1
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": (
                    "Your response was not valid JSON matching the required schema. "
                    "Please respond with only the JSON Decision object. "
                    "No markdown, no explanation text — raw JSON only."
                ),
            })
            continue

        reason = _legality_failure_reason(decision, brief_state)
        if reason is None:
            reason = _plan_consistency_failure_reason(
                decision=decision,
                brief_state=brief_state,
                plan=plan,
                strict_plan_check=strict_plan_check,
            )
        if reason is not None:
            metrics["legality_retries"] += 1
            if validator_retries >= max_validator_retries:
                return _finish(
                    _PASS_DECISION,
                    f"pass (validator budget exhausted; last reason: {reason})",
                )
            validator_retries += 1
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": reason})
            continue

        logger.info(
            "Decision [round=%d]: action=%s reasoning=%.120s",
            round_num,
            decision.move.action,
            decision.reasoning,
        )
        return _finish(
            decision,
            f"{decision.move.action} (after {len(tool_trace)} tool call(s))",
        )

    return _finish(_PASS_DECISION, "pass (exhausted MAX_TOOL_ROUNDS without a decision)")


async def _decide_legacy(
    *,
    brief_state: dict,
    game_id: str,
    memory: Memory,
    rejection_context: Optional[dict],
    metrics: dict,
) -> Decision:
    model = os.environ.get("RIFTBOUND_AI_MODEL", DEFAULT_MODEL)
    skill_module.set_history_context(memory, game_id)
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": build_system_prompt(brief_state)},
    ]
    timeline = memory.timeline_slice(game_id)
    if timeline:
        messages.append({"role": "user", "content": timeline})
    user_content = f"## Current Decision\n\n{_format_brief_state(brief_state)}"
    user_content += _format_rejection_context(rejection_context)
    messages.append({"role": "user", "content": user_content})
    _log_input(game_id, brief_state, messages)
    return await _run_actor_loop(
        model=model,
        brief_state=brief_state,
        game_id=game_id,
        messages=messages,
        metrics=metrics,
    )


async def _decide_staged(
    *,
    brief_state: dict,
    game_id: str,
    memory: Memory,
    rejection_context: Optional[dict],
    metrics: dict,
) -> Decision:
    model = os.environ.get("RIFTBOUND_AI_MODEL", DEFAULT_MODEL)
    skill_module.set_history_context(memory, game_id)
    route = router_module.route(brief_state)
    if route.forced_command:
        forced = _forced_decision(route.forced_command)
        if forced is not None:
            return forced

    plan: Plan | None = None
    timeline = memory.timeline_slice(game_id)
    if route.needs_plan:
        opponent_action_count = memory.count_opponent_material_actions(game_id)
        plan, was_cached = await _planner.plan(
            client=get_client(),
            model=model,
            game_id=game_id,
            brief_state=brief_state,
            memory_summary=timeline,
            opponent_action_count=opponent_action_count,
            metrics=metrics,
        )
        decision_index = memory._decision_counters.get(game_id, 0)
        _log_plan(
            game_id,
            brief_state,
            plan,
            was_cached=was_cached,
            decision_index=decision_index,
        )

    system = build_system_prompt_from_modules(route.modules, brief_state=brief_state)
    messages: list[ChatCompletionMessageParam] = [{"role": "system", "content": system}]
    if timeline:
        messages.append({"role": "user", "content": timeline})

    brief_summary = _format_brief_state(brief_state)
    user_content = f"## Current Decision\n\n{brief_summary}"
    if plan is not None:
        user_content += (
            "\n\n## Turn Plan (guidance, not binding)\n"
            "Use this as your default strategic direction for the turn, but you "
            "may deviate when a clearly better legal move is available — explain "
            "the deviation in your reasoning.\n"
            f"{plan.model_dump_json(indent=2)}"
        )
    user_content += _format_rejection_context(rejection_context)
    messages.append({"role": "user", "content": user_content})
    _log_input(game_id, brief_state, messages)

    return await _run_actor_loop(
        model=model,
        brief_state=brief_state,
        game_id=game_id,
        messages=messages,
        metrics=metrics,
        strict_plan_check=route.strict_plan_check,
        plan=plan,
        max_validator_retries=1,
    )


# ── Brief state formatting ────────────────────────────────────────────────────

def _head_label(verb: str, head: tuple[str, ...]) -> str:
    if not head:
        return verb
    return f"{verb} {' '.join(head)}"


def _ordered_values(values: set[str]) -> list[str]:
    ordered = sorted(values)
    if "base" in values:
        ordered = ["base"] + [v for v in ordered if v != "base"]
    return ordered


# Moves that take no parameters and act as turn/priority terminators; shown
# last so the action options read first.
_TERMINAL_MOVES = frozenset({"end turn", "pass", "assign done", "choose none", "mulligan keep"})


def _build_legal_move_option_lines(legal: list[str]) -> list[str]:
    """Collapse the enumerated legal moves into one line per move identity.

    All enumerated strings that share the same verb + head (card/unit ids) are
    merged into a single line whose parameter slots list every legal value, e.g.
    ``play noxus-hopeful [to: base|battlefield-a|battlefield-b; flags: accelerate]``.
    This replaces the previous flat expansion where each destination/target was
    its own line.
    """
    destination_verbs = {"play", "move"}
    grouped: dict[tuple[str, tuple[str, ...]], dict[str, set[str]]] = {}
    order: list[tuple[str, tuple[str, ...]]] = []
    raw_moves: list[str] = []

    for move in legal:
        parsed = _parse_command(move)
        if parsed is None:
            raw_moves.append(move)
            continue

        key = (parsed["verb"], parsed["head"])
        if key not in grouped:
            grouped[key] = {"to": set(), "target": set(), "at": set(), "flags": set()}
            order.append(key)
        entry = grouped[key]
        if parsed["to"] is not None:
            entry["to"].add(parsed["to"])
        elif parsed["verb"] in destination_verbs:
            entry["to"].add("base")
        if parsed["target"] is not None:
            entry["target"].add(parsed["target"])
        if parsed["at"] is not None:
            entry["at"].add(parsed["at"])
        for flag in parsed["flags"]:
            entry["flags"].add(flag)

    def _line_for(key: tuple[str, tuple[str, ...]]) -> str:
        verb, head = key
        params = grouped[key]
        parts: list[str] = []
        if params["to"]:
            parts.append("to: " + "|".join(_ordered_values(params["to"])))
        if params["at"]:
            parts.append("at: " + "|".join(_ordered_values(params["at"])))
        if params["target"]:
            parts.append("target: " + "|".join(_ordered_values(params["target"])))
        if params["flags"]:
            parts.append("flags: " + "|".join(sorted(params["flags"])))
        suffix = f" [{'; '.join(parts)}]" if parts else ""
        return f"{_head_label(verb, head)}{suffix}"

    # Action moves first (in enumeration order), terminal moves last.
    action_keys = [k for k in order if _head_label(*k) not in _TERMINAL_MOVES]
    terminal_keys = [k for k in order if _head_label(*k) in _TERMINAL_MOVES]

    lines = [f"    {_line_for(k)}" for k in action_keys]
    lines.extend(f"    {move}" for move in raw_moves if move not in _TERMINAL_MOVES)
    lines.extend(f"    {_line_for(k)}" for k in terminal_keys)
    lines.extend(f"    {move}" for move in raw_moves if move in _TERMINAL_MOVES)
    return lines


def _append_legal_moves(lines: list[str], legal: list) -> None:
    """Render legal moves as one line per move with parameter choices inline."""
    lines.append(f"Legal moves ({len(legal)} total) — pick ONE value per [slot]:")
    option_lines = _build_legal_move_option_lines(legal)
    if option_lines:
        lines.extend(option_lines)
    else:
        lines.append("    (none)")
    typed = _typed_legal_actions(legal)
    if typed:
        lines.append("  Typed legal actions:")
        lines.append("```json")
        lines.append(json.dumps([a.model_dump() for a in typed], indent=2))
        lines.append("```")
    lines.append("  Use list_legal_moves for a fresh full list if needed.")


def _typed_legal_actions(legal_moves: list[str]) -> list[LegalActionOption]:
    typed: list[LegalActionOption] = []
    for cmd in legal_moves:
        move = _move_from_command(cmd)
        if move is None:
            continue
        typed.append(
            LegalActionOption(
                action=move.action,
                params=move.parameters,
                label=cmd,
                raw_command=cmd,
            )
        )
    return typed


def _format_acting_context(bs: dict) -> str:
    """Summarize Focus vs Priority for the current seat."""
    focus_you = bs.get("i_have_focus", False)
    priority_you = bs.get("i_have_priority", False)
    focus_str = "you" if focus_you else "opponent"
    priority_str = "you" if priority_you else "opponent"
    chain_active = bool(bs.get("legal_moves")) and bs.get("decision_type") == "chain_reaction"
    chain_note = " | Chain active" if chain_active else ""
    return f"Acting context: Focus={focus_str} | Priority={priority_str}{chain_note}"


def _unit_role_tag(u: dict) -> str:
    """Return ' ATK'/' DEF' when a unit is designated in an active showdown."""
    if u.get("is_attacker"):
        return " ATK"
    if u.get("is_defender"):
        return " DEF"
    return ""


def _format_brief_state(bs: dict) -> str:
    """Render the brief state as a readable text summary for the model."""
    lines: list[str] = []

    lines.append(f"Turn {bs.get('turn_number', '?')} | "
                 f"Phase: {bs.get('current_phase', '?')} | "
                 f"State: {bs.get('current_state', '?')} | "
                 f"Decision type: **{bs.get('decision_type', '?')}**")
    lines.append(_format_acting_context(bs))
    lines.append(f"My score: {bs.get('my_score', 0)} | "
                 f"Opponent score: {bs.get('opponent_score', 0)} | "
                 f"Victory: 8 pts")
    lines.append("")

    # Resources — compute total playable energy from pool + untapped runes
    runes = bs.get("my_runes", [])
    untapped_runes = [r for r in runes if not r.get("is_exhausted", False)]
    exhausted_runes = [r for r in runes if r.get("is_exhausted", False)]
    pool_energy = bs.get("my_energy", 0)
    pool_power: dict = bs.get("my_power", {}) or {}
    total_energy = pool_energy + len(untapped_runes)

    # Domain power available = pool power + one per untapped rune of that domain
    total_power: dict[str, int] = dict(pool_power)
    for r in untapped_runes:
        d = r.get("domain", "")
        total_power[d] = total_power.get(d, 0) + 1

    # Compact rune summary: "3 untapped (1 fury, 2 mind) | 1 exhausted (1 fury)"
    untapped_by_domain: dict[str, int] = {}
    for r in untapped_runes:
        d = r.get("domain", "")
        untapped_by_domain[d] = untapped_by_domain.get(d, 0) + 1
    exhausted_by_domain: dict[str, int] = {}
    for r in exhausted_runes:
        d = r.get("domain", "")
        exhausted_by_domain[d] = exhausted_by_domain.get(d, 0) + 1
    untapped_summary = ", ".join(
        f"{n} {d}" for d, n in sorted(untapped_by_domain.items())
    ) or "none"
    exhausted_summary = ", ".join(
        f"{n} {d}" for d, n in sorted(exhausted_by_domain.items())
    )
    rune_summary = f"{len(untapped_runes)} untapped ({untapped_summary})"
    if exhausted_runes:
        rune_summary += f" | {len(exhausted_runes)} exhausted ({exhausted_summary})"
    power_str = (
        "  " + " ".join(f"{d.upper()[:3]}×{n}" for d, n in sorted(total_power.items()))
        if total_power else ""
    )
    lines.append(f"Resources: {total_energy}E playable{power_str}  [{rune_summary}]")

    # Floating energy/power: only shown when the pool has non-zero values from
    # card effects or abilities (rare — normally the pool is empty at Main Phase).
    floating_power = {d: v for d, v in pool_power.items() if v > 0}
    if pool_energy > 0 or floating_power:
        extra_parts = []
        if pool_energy > 0:
            extra_parts.append(f"+{pool_energy}E")
        for d, v in sorted(floating_power.items()):
            extra_parts.append(f"+{v} {d.upper()[:3]}")
        lines.append(f"  (includes {' '.join(extra_parts)} floating from card/ability effects)")

    lines.append("")

    # Hand — costs and keywords for planning; legality comes from legal_moves
    hand = bs.get("my_hand", [])
    lines.append(f"Hand ({len(hand)} cards):")
    for c in hand:
        e_cost = c.get("energy_cost", 0)
        p_costs: list = c.get("power_cost", []) or []
        cost_str = f"{e_cost}E"
        if p_costs:
            cost_str += "+" + "+".join(
                f"{pc['amount']}{pc['domain'][:3].upper()}" for pc in p_costs
            )
        kw = ", ".join(c.get("keywords", []))
        might_str = f" Might:{c['might']}" if c.get("might") is not None else ""
        lines.append(
            f"  {c['instance_id']} — {c['name']} [{c['card_type']}] ({cost_str})"
            f"{might_str} {kw}".rstrip()
        )
        effect = c.get("effect_text", "")
        if effect:
            lines.append(f"    Effect: {skill_module.format_effect_text(effect)}")
    lines.append("")

    # Board
    my_base = bs.get("my_base_units", [])
    if my_base:
        lines.append("My base units: " + ", ".join(
            f"{u['instance_id']}({u['current_might']}MHT{'*' if u['is_exhausted'] else ''})"
            for u in my_base
        ))
    opp_base = bs.get("opponent_base_units", [])
    if opp_base:
        lines.append("Opponent base units: " + ", ".join(
            f"{u['instance_id']}({u['current_might']}MHT{'*' if u['is_exhausted'] else ''})"
            for u in opp_base
        ))
    lines.append(f"Opponent hand size: {bs.get('opponent_hand_size', 0)}")
    lines.append("")

    # Battlefields
    for bf in bs.get("battlefields", []):
        ctrl = bf.get("controller_index", -1)
        ctrl_str = "uncontrolled" if ctrl == -1 else f"P{ctrl + 1}"
        contested = " CONTESTED" if bf.get("is_contested") else ""
        all_bf_units = (bf.get("my_units") or []) + (bf.get("opponent_units") or [])
        showdown = " SHOWDOWN" if any(
            u.get("is_attacker") or u.get("is_defender") for u in all_bf_units
        ) else ""
        lines.append(f"[{bf['battlefield_id']}] {bf['display_name']} — {ctrl_str}{contested}{showdown}")
        bf_effect = bf.get("effect_text", "")
        if bf_effect:
            lines.append(f"  Effect: {skill_module.format_effect_text(bf_effect)}")
        if bf.get("my_units"):
            lines.append("  My units: " + ", ".join(
                f"{u['instance_id']}({u['current_might']}MHT{_unit_role_tag(u)})"
                for u in bf["my_units"]
            ))
        if bf.get("opponent_units"):
            lines.append("  Opp units: " + ", ".join(
                f"{u['instance_id']}({u['current_might']}MHT{_unit_role_tag(u)})"
                for u in bf["opponent_units"]
            ))
        my_facedown = bf.get("my_facedown")
        if my_facedown:
            fd_cost = my_facedown.get("play_from_hidden_cost", "0E")
            lines.append(
                f"  My hidden: {my_facedown['instance_id']} ({my_facedown['name']}) "
                f"— play from hidden costs {fd_cost}"
            )
            fd_effect = my_facedown.get("effect_text", "")
            if fd_effect:
                lines.append(f"    Effect: {skill_module.format_effect_text(fd_effect)}")
        elif bf.get("has_facedown"):
            lines.append("  Hidden card present (opponent's)")
    lines.append("")

    # Legal moves — sole source of truth for what you may do this decision
    legal = bs.get("legal_moves", [])
    if legal:
        _append_legal_moves(lines, legal)

    # Decision context — pending choice
    ctx = bs.get("pending_choice_context", {})
    if hasattr(ctx, "model_dump"):
        ctx = ctx.model_dump()
    opts = bs.get("pending_choice_options", [])
    if ctx or opts:
        lines.append("")
        lines.append("=== PENDING CHOICE ===")
        if ctx.get("prompt_type"):
            lines.append(f"Type: {ctx['prompt_type']}")
        if ctx.get("prompt_text"):
            lines.append(f"What: {ctx['prompt_text']}")
        if ctx.get("source_card_name"):
            lines.append(f"Source: {ctx['source_card_name']} (id: {ctx.get('source_card_id', '?')})")
        if ctx.get("source_effect_text"):
            lines.append(
                f"Source effect: {skill_module.format_effect_text(str(ctx['source_effect_text']))}"
            )
        if ctx.get("ability_description"):
            lines.append(f"Ability: {ctx['ability_description']}")
        if ctx.get("remaining_discards") is not None:
            mandatory = ctx.get("mandatory", True)
            lines.append(
                f"Discards: {ctx['remaining_discards']} remaining"
                f" ({'mandatory' if mandatory else 'optional'})"
            )
        if opts:
            lines.append(f"Options (use choose <option>): {opts}")
        lines.append("======================")

    if bs.get("combat_assignment_active"):
        lines.append(f"Combat assignment active. Remaining attacker might: {bs.get('remaining_attacker_might', 0)}")
        lines.append(f"Already assigned: {bs.get('damage_assigned', {})}")

    return "\n".join(lines)
