"""Per-turn budget and memoization for Phase-3 live engine tools."""
from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolBudget:
    node_limit: int = 1500
    time_limit_ms: int = 3000
    nodes_used: int = 0
    engine_time_ms: int = 0
    simulate_cache: dict[tuple[str, ...], dict[str, Any]] = field(default_factory=dict)

    @property
    def nodes_remaining(self) -> int:
        return max(0, self.node_limit - self.nodes_used)

    @property
    def time_remaining_ms(self) -> int:
        return max(0, self.time_limit_ms - self.engine_time_ms)

    @property
    def exhausted(self) -> bool:
        return self.nodes_remaining <= 0 or self.time_remaining_ms <= 0

    @property
    def remaining_pct(self) -> int:
        node_pct = self.nodes_remaining / max(1, self.node_limit)
        time_pct = self.time_remaining_ms / max(1, self.time_limit_ms)
        return max(0, min(100, int(round(min(node_pct, time_pct) * 100))))

    def clamp_search_payload(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if self.exhausted:
            return None
        out = dict(payload)
        requested = dict(out.get("budget", {}) or {})
        requested_nodes = max(1, int(requested.get("node_budget", self.nodes_remaining)))
        requested_ms = max(1, int(requested.get("time_budget_ms", self.time_remaining_ms)))
        requested["node_budget"] = min(requested_nodes, self.nodes_remaining)
        requested["time_budget_ms"] = min(requested_ms, self.time_remaining_ms)
        out["budget"] = requested
        return out

    def record_search(
        self,
        result: dict[str, Any],
        elapsed_ms: int,
        requested_nodes: int,
    ) -> None:
        stats = result.get("search_stats", {}) if isinstance(result, dict) else {}
        if not isinstance(stats, dict):
            stats = {}
        explored = int(stats.get("nodes_explored", requested_nodes) or requested_nodes)
        self.nodes_used = min(
            self.node_limit,
            self.nodes_used + max(0, explored),
        )
        reported_ms = max(0, int(stats.get("elapsed_ms", elapsed_ms) or elapsed_ms))
        self.engine_time_ms += reported_ms

    def status(self) -> dict[str, int | bool]:
        return {
            "node_limit": self.node_limit,
            "time_limit_ms": self.time_limit_ms,
            "nodes_used": self.nodes_used,
            "engine_time_ms": self.engine_time_ms,
            "nodes_remaining": self.nodes_remaining,
            "time_remaining_ms": self.time_remaining_ms,
            "budget_remaining_pct": self.remaining_pct,
            "budget_exhausted": self.exhausted,
        }


_CURRENT_BUDGET: ContextVar[ToolBudget | None] = ContextVar(
    "riftbound_tool_budget", default=None
)


def current_budget() -> ToolBudget | None:
    return _CURRENT_BUDGET.get()


def install_budget(budget: ToolBudget) -> Token:
    return _CURRENT_BUDGET.set(budget)


def reset_budget(token: Token) -> None:
    _CURRENT_BUDGET.reset(token)


def budget_exhausted_result() -> dict[str, Any]:
    budget = current_budget()
    status = budget.status() if budget else {}
    return {
        "legal": False,
        "source": "budget",
        "error": "budget_exhausted",
        **status,
    }

