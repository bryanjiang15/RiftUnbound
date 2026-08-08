"""CLI for Riftbound AI evaluation.

Usage:
  python -m ai_agent.eval validate-corpus
  python -m ai_agent.eval render-catalog
  python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/blocking.json
  python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/engine-contract-smoke.json
  python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/agent-argmax-smoke.json
  python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/reasoner-live-smoke.json
  python -m ai_agent.eval report --run-dir Data/AI/Eval/runs/<run_id>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Load repo .env before adapters create the OpenAI client.
from .env import ensure_dotenv

ensure_dotenv()

from .arena import analyze_pairs, expand_pairs, load_arena_manifest
from .corpus import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_POSITIONS_DIR,
    load_corpus,
    validate_corpus,
    write_catalog,
)
from .runner import DEFAULT_PROFILES_DIR, DEFAULT_RUNS_DIR, run_eval
from .schemas import EvalRunManifest
from .transforms import available_transforms


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ai_agent.eval")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate-corpus", help="Validate position JSON + fixtures")
    p_val.add_argument("--positions", default=str(DEFAULT_POSITIONS_DIR))

    p_cat = sub.add_parser("render-catalog", help="Regenerate Markdown position catalog")
    p_cat.add_argument("--positions", default=str(DEFAULT_POSITIONS_DIR))
    p_cat.add_argument("--out", default=str(DEFAULT_CATALOG_PATH))

    p_run = sub.add_parser("run", help="Run an evaluation manifest")
    p_run.add_argument("--manifest", required=True)
    p_run.add_argument("--positions", default=str(DEFAULT_POSITIONS_DIR))
    p_run.add_argument("--profiles", default=str(DEFAULT_PROFILES_DIR))
    p_run.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))

    p_rep = sub.add_parser("report", help="Print an existing run report")
    p_rep.add_argument("--run-dir", required=True)

    p_tr = sub.add_parser("list-transforms", help="List metamorphic transforms")

    p_ar = sub.add_parser("expand-arena", help="Expand arena manifest into pair legs")
    p_ar.add_argument("--manifest", required=True)
    p_ar.add_argument("--out", help="Optional JSON output path")

    args = parser.parse_args(argv)

    if args.cmd == "validate-corpus":
        errors = validate_corpus(args.positions)
        if errors:
            print("Corpus validation FAILED:")
            for err in errors:
                print(f"  - {err}")
            return 1
        cases = load_corpus(
            args.positions,
            splits=["dev", "sealed", "challenge", "blocking"],
            include_fidelity_limited=True,
        )
        print(f"Corpus OK — {len(cases)} positions")
        return 0

    if args.cmd == "render-catalog":
        path = write_catalog(positions_dir=args.positions, catalog_path=args.out)
        print(f"Wrote {path}")
        return 0

    if args.cmd == "run":
        manifest = EvalRunManifest.model_validate(
            json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        )
        run_dir = run_eval(
            manifest,
            positions_dir=args.positions,
            profiles_dir=args.profiles,
            runs_dir=args.runs_dir,
        )
        print(f"Run complete: {run_dir}")
        print(f"Report: {run_dir / 'report.md'}")
        return 0

    if args.cmd == "report":
        report = Path(args.run_dir) / "report.md"
        if not report.exists():
            print(f"missing report: {report}", file=sys.stderr)
            return 1
        print(report.read_text(encoding="utf-8"))
        return 0

    if args.cmd == "list-transforms":
        for name in available_transforms():
            print(name)
        return 0

    if args.cmd == "expand-arena":
        manifest = load_arena_manifest(args.manifest)
        jobs = expand_pairs(manifest)
        analysis_stub = analyze_pairs([])
        payload = {"jobs": jobs, "analysis_notes": analysis_stub["note"], "count": len(jobs)}
        text = json.dumps(payload, indent=2)
        if args.out:
            Path(args.out).write_text(text + "\n", encoding="utf-8")
            print(f"Wrote {args.out} ({len(jobs)} legs)")
        else:
            print(text)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
