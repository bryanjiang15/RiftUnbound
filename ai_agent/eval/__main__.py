"""CLI for Riftbound AI evaluation.

Usage:
  python -m ai_agent.eval validate-corpus
  python -m ai_agent.eval render-catalog
  python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/blocking.json
  python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/engine-contract-smoke.json
  python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/agent-argmax-smoke.json
  python -m ai_agent.eval run --manifest Data/AI/Eval/manifests/reasoner-live-smoke.json
  python -m ai_agent.eval report --run-dir Data/AI/Eval/runs/<run_id>
  python -m ai_agent.eval investigate-report --run-dir Data/AI/Eval/runs/<run_id>
  python -m ai_agent.eval investigate-baseline
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Load repo .env before adapters create the OpenAI client.
from .env import ensure_dotenv

ensure_dotenv()

from .arena import (
    analyze_pairs,
    expand_pairs,
    load_arena_manifest,
    write_sprt_report,
)
from .corpus import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_POSITIONS_DIR,
    load_corpus,
    validate_corpus,
    write_catalog,
)
from .investigate_report import archive_baseline_stub, write_investigation_report
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

    p_inv = sub.add_parser(
        "investigate-report",
        help="Write investigation-quality metrics from an existing eval run",
    )
    p_inv.add_argument("--run-dir", required=True)

    p_base = sub.add_parser(
        "investigate-baseline",
        help="Archive a §5.3-style investigation baseline report under Data/AI/Eval/runs",
    )
    p_base.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    p_base.add_argument("--run-id", default=None)
    p_base.add_argument(
        "--from-run-dir",
        default=None,
        help="Optional existing eval run to summarize instead of the synthetic stub",
    )

    p_sprt = sub.add_parser(
        "sprt-report",
        help="Analyze arena pair JSONL and write an SPRT strength report",
    )
    p_sprt.add_argument(
        "--pairs-jsonl",
        required=True,
        help="JSONL of aggregate pair records (both_finished, candidate_wins, ...)",
    )
    p_sprt.add_argument("--out", required=True, help="Markdown report output path")

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

    if args.cmd == "investigate-report":
        path = write_investigation_report(args.run_dir)
        print(f"Wrote {path}")
        return 0

    if args.cmd == "investigate-baseline":
        if args.from_run_dir:
            src = Path(args.from_run_dir)
            out = write_investigation_report(
                src,
                title="Reasoner investigation baseline (§5.3 harness)",
                extra={"baseline_kind": "from_existing_run", "source_run": str(src)},
            )
            print(f"Wrote {out}")
            return 0
        run_dir = archive_baseline_stub(args.runs_dir, run_id=args.run_id)
        print(f"Archived baseline: {run_dir}")
        print(f"Report: {run_dir / 'investigation_report.md'}")
        return 0

    if args.cmd == "sprt-report":
        pairs: list[dict] = []
        for line in Path(args.pairs_jsonl).read_text(encoding="utf-8").splitlines():
            if line.strip():
                pairs.append(json.loads(line))
        path = write_sprt_report(pairs, args.out)
        print(f"Wrote {path}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
