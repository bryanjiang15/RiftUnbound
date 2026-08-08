"""Corpus loading, fixture hashing, and catalog generation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from .schemas import EvalCase

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POSITIONS_DIR = REPO_ROOT / "Data" / "AI" / "Eval" / "positions"
DEFAULT_CATALOG_PATH = REPO_ROOT / "ai_agent" / "docs" / "AI_Evaluation_Position_Catalog.md"


def fixture_abs_path(fixture_path: str) -> Path:
    if fixture_path.startswith("res://"):
        return REPO_ROOT / fixture_path.removeprefix("res://")
    path = Path(fixture_path)
    return path if path.is_absolute() else REPO_ROOT / path


def hash_fixture(fixture_path: str) -> str:
    path = fixture_abs_path(fixture_path)
    if not path.exists():
        return ""
    raw = path.read_bytes()
    return hashlib.sha256(raw).hexdigest()[:16]


def load_case(path: Path) -> EvalCase:
    data = json.loads(path.read_text(encoding="utf-8"))
    case = EvalCase.model_validate(data)
    if not case.fixture_hash:
        case.fixture_hash = hash_fixture(case.fixture_path)
    return case


def load_corpus(
    positions_dir: Path | str = DEFAULT_POSITIONS_DIR,
    *,
    splits: Iterable[str] | None = None,
    include_fidelity_limited: bool = False,
    eval_lanes: Iterable[str] | None = None,
    case_globs: Iterable[str] | None = None,
) -> list[EvalCase]:
    root = Path(positions_dir)
    lane_filter = set(eval_lanes) if eval_lanes is not None else None
    glob_patterns = list(case_globs) if case_globs is not None else ["*.json"]
    paths: list[Path] = []
    seen: set[Path] = set()
    for pattern in glob_patterns:
        for path in sorted(root.glob(pattern)):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            paths.append(path)
    cases: list[EvalCase] = []
    for path in sorted(paths, key=lambda p: p.name):
        case = load_case(path)
        if splits is not None and case.split not in set(splits):
            continue
        if not include_fidelity_limited and case.fidelity_status != "authoritative":
            continue
        if lane_filter is not None and case.eval_lane not in lane_filter:
            continue
        cases.append(case)
    return cases


def validate_corpus(positions_dir: Path | str = DEFAULT_POSITIONS_DIR) -> list[str]:
    """Return human-readable validation errors (empty = ok)."""
    errors: list[str] = []
    root = Path(positions_dir)
    if not root.exists():
        return [f"positions directory missing: {root}"]
    seen: set[str] = set()
    for path in sorted(root.glob("*.json")):
        try:
            case = load_case(path)
        except Exception as exc:  # noqa: BLE001 - surface all validation failures
            errors.append(f"{path.name}: invalid schema ({exc})")
            continue
        if case.case_id in seen:
            errors.append(f"{path.name}: duplicate case_id {case.case_id}")
        seen.add(case.case_id)
        fixture = fixture_abs_path(case.fixture_path)
        if not fixture.exists():
            errors.append(f"{case.case_id}: missing fixture {case.fixture_path}")
            continue
        digest = hash_fixture(case.fixture_path)
        if case.fixture_hash and case.fixture_hash != digest:
            errors.append(
                f"{case.case_id}: fixture_hash mismatch "
                f"(case={case.fixture_hash}, file={digest})"
            )
        if not case.acceptable_outcomes and case.label_tier == "gold":
            errors.append(f"{case.case_id}: gold case missing acceptable_outcomes")
    return errors


def render_catalog(cases: list[EvalCase]) -> str:
    lines = [
        "# AI Evaluation Position Catalog",
        "",
        "Generated from `Data/AI/Eval/positions/*.json`. Do not hand-edit;",
        "regenerate with `python -m ai_agent.eval render-catalog`.",
        "",
        f"Total positions: **{len(cases)}**",
        "",
    ]
    by_split: dict[str, list[EvalCase]] = {}
    for case in cases:
        by_split.setdefault(case.split, []).append(case)

    for split in ("blocking", "dev", "sealed", "challenge"):
        group = by_split.get(split, [])
        if not group:
            continue
        lines.append(f"## {split.title()} ({len(group)})")
        lines.append("")
        for case in group:
            lines.extend(_case_section(case))
    return "\n".join(lines).rstrip() + "\n"


def _case_section(case: EvalCase) -> list[str]:
    outcomes = "; ".join(
        f"{o.kind}: {o.description or o.params}" for o in case.acceptable_outcomes
    ) or "(none)"
    traps = "; ".join(
        f"{o.kind}: {o.description or o.params}" for o in (case.trap_outcomes or [])
    ) or "(none)"
    invariants = "; ".join(
        f"{inv.kind}: {inv.description or inv.params}" for inv in case.hard_invariants
    ) or "(none)"
    return [
        f"### `{case.case_id}` — {case.title}",
        "",
        f"- **Summary:** {case.summary}",
        f"- **Objective:** {case.objective}",
        f"- **Desired result:** {case.desired_result}",
        f"- **Fixture:** `{case.fixture_path}` (hash `{case.fixture_hash or 'unset'}`)",
        f"- **Seat / decision:** seat {case.acting_seat}, `{case.decision_type}`",
        f"- **Label / fidelity:** {case.label_tier} / {case.fidelity_status}",
        f"- **Eval lane:** `{case.eval_lane}` (engine = Godot contracts, no LLM; agent = decision quality)",
        f"- **Tags:** {', '.join(case.tags) or '(none)'}",
        f"- **Setup:** {case.setup_notes or case.summary}",
        f"- **Hard invariants:** {invariants}",
        f"- **Acceptable outcomes:** {outcomes}",
        f"- **Trap outcomes:** {traps}",
        f"- **Exclusions:** {case.exclusions or 'none'}",
        f"- **Source:** {case.provenance.source_test or case.provenance.source_fixture or 'n/a'}",
        "",
    ]


def write_catalog(
    cases: list[EvalCase] | None = None,
    *,
    positions_dir: Path | str = DEFAULT_POSITIONS_DIR,
    catalog_path: Path | str = DEFAULT_CATALOG_PATH,
) -> Path:
    if cases is None:
        cases = load_corpus(
            positions_dir,
            splits=["dev", "sealed", "challenge", "blocking"],
            include_fidelity_limited=True,
        )
    out = Path(catalog_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_catalog(cases), encoding="utf-8")
    return out
