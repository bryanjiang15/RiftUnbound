"""Request-scoped state and verified engine-line registry for the Reasoner."""
from __future__ import annotations

import hashlib
import re
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any


def _commands(line: dict[str, Any]) -> list[str]:
    from .skills import _move_to_command

    return [_move_to_command(move) for move in (line.get("moves", []) or [])]


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return text or "line"


@dataclass
class VerifiedLineRegistry:
    """Canonical request-local registry of engine-produced candidate lines."""

    root_state_hash: str
    _by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    _by_sequence: dict[tuple[str, ...], str] = field(default_factory=dict)

    def register(
        self,
        line: dict[str, Any],
        *,
        source: str,
    ) -> dict[str, Any] | None:
        moves = _commands(line)
        if not moves:
            return None
        sequence = tuple(moves)
        lineage = str(source or "engine")
        existing_id = self._by_sequence.get(sequence)
        if existing_id is not None:
            existing = self._by_id[existing_id]
            sources = existing.setdefault("source_lineage", [])
            if lineage not in sources:
                sources.append(lineage)
            became_complete = bool(line.get("complete")) and not bool(
                existing.get("complete")
            )
            if became_complete:
                for key in (
                    "move_contexts",
                    "expected_pre_hashes",
                    "score",
                    "score_breakdown",
                    "features",
                    "resolved_state",
                    "search_state",
                    "opponent_windows",
                    "terminal_reason",
                    "search_mode",
                    "root_state_hash",
                ):
                    if key in line:
                        existing[key] = line[key]
            # Prefer newly supplied executable metadata without changing identity.
            for key in (
                "move_contexts",
                "expected_pre_hashes",
                "score_breakdown",
                "features",
                "resolved_state",
                "search_state",
                "opponent_windows",
                "terminal_reason",
                "search_mode",
            ):
                if line.get(key) and not existing.get(key):
                    existing[key] = line[key]
            existing["complete"] = bool(existing.get("complete")) or bool(line.get("complete"))
            existing["legal"] = bool(existing.get("legal", True)) and bool(line.get("legal", True))
            return dict(existing)

        original_id = str(line.get("line_id", "") or "line")
        digest = hashlib.sha256("\x1f".join(sequence).encode("utf-8")).hexdigest()[:10]
        canonical_id = f"{_slug(lineage)}-{_slug(original_id)}-{digest}"
        suffix = 2
        base_id = canonical_id
        while canonical_id in self._by_id:
            canonical_id = f"{base_id}-{suffix}"
            suffix += 1

        entry = dict(line)
        entry.update({
            "line_id": canonical_id,
            "original_line_id": original_id,
            "source_lineage": [lineage],
            "moves": moves,
            "root_state_hash": str(
                line.get("root_state_hash") or self.root_state_hash
            ),
            "legal": bool(line.get("legal", True)),
            "complete": bool(line.get("complete", False)),
            "terminal_reason": str(line.get("terminal_reason", "")),
            "search_mode": str(line.get("search_mode", "main")),
        })
        entry.setdefault("move_contexts", [])
        entry.setdefault("expected_pre_hashes", [])
        entry.setdefault("opponent_windows", [])
        self._by_id[canonical_id] = entry
        self._by_sequence[sequence] = canonical_id
        return dict(entry)

    def register_many(
        self,
        lines: list[dict[str, Any]] | None,
        *,
        source: str,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for line in lines or []:
            if not isinstance(line, dict):
                continue
            registered = self.register(line, source=source)
            if (
                registered is not None
                and str(registered.get("line_id", "")) not in seen_ids
            ):
                out.append(registered)
                seen_ids.add(str(registered.get("line_id", "")))
        return out

    def get(self, line_id: str | None) -> dict[str, Any] | None:
        if not line_id:
            return None
        line = self._by_id.get(str(line_id))
        return dict(line) if line is not None else None

    def restore(self, line: dict[str, Any]) -> None:
        """Restore a previously validated canonical entry on an exact-root cache hit."""
        canonical_id = str(line.get("line_id", "") or "")
        moves = tuple(_commands(line))
        if not canonical_id or not moves:
            return
        entry = dict(line)
        entry["moves"] = list(moves)
        self._by_id[canonical_id] = entry
        self._by_sequence[moves] = canonical_id

    def lines(self) -> list[dict[str, Any]]:
        return [dict(line) for line in self._by_id.values()]

    @property
    def unique_sequence_count(self) -> int:
        return len(self._by_sequence)


@dataclass
class ReasonerTurnContext:
    game_id: str
    brief_state: dict[str, Any]
    root_state_hash: str
    memory: Any = None
    memory_summary: str = ""
    scout_stats: dict[str, Any] = field(default_factory=dict)
    scout_lines: list[dict[str, Any]] = field(default_factory=list)
    search_corpus: list[dict[str, Any]] = field(default_factory=list)
    budget: Any = None
    registry: VerifiedLineRegistry = field(init=False)
    telemetry: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.registry = VerifiedLineRegistry(self.root_state_hash)


_CURRENT_CONTEXT: ContextVar[ReasonerTurnContext | None] = ContextVar(
    "riftbound_reasoner_turn_context", default=None
)


def current_context() -> ReasonerTurnContext | None:
    return _CURRENT_CONTEXT.get()


def install_context(context: ReasonerTurnContext) -> Token:
    return _CURRENT_CONTEXT.set(context)


def reset_context(token: Token) -> None:
    _CURRENT_CONTEXT.reset(token)
