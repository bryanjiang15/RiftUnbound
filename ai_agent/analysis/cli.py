"""CLI for Phase 2 move-quality judges.

  python -m ai_agent.analysis counterfactual --db ... --game-id ... --turn ... --decision-index ...
  python -m ai_agent.analysis failure-report --db ... --game-id ... --turn ... --decision-index ...
  python -m ai_agent.analysis wpa --db ... [--origin self_play]
  python -m ai_agent.analysis validate-db --db ...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..memory import Memory
from . import counterfactual as cf
from . import failure_modes as fm
from . import wpa_report


def _memory(db: Path | None) -> Memory:
    return Memory(db_path=db) if db is not None else Memory()


def cmd_counterfactual(args: argparse.Namespace) -> int:
    memory = _memory(args.db)
    result = cf.analyze_decision(
        memory,
        game_id=args.game_id,
        turn=args.turn,
        decision_index=args.decision_index,
        persist=not args.no_persist,
    )
    if args.format == "json":
        print(json.dumps(result, default=str, indent=2))
    else:
        print(cf.render_markdown(result))
    return 0 if result.get("ok") or result.get("status") == "ok" else 1


def cmd_failure_report(args: argparse.Namespace) -> int:
    memory = _memory(args.db)
    bundle = cf.load_decision_bundle(
        memory,
        game_id=args.game_id,
        turn=args.turn,
        decision_index=args.decision_index,
    )
    cf_result = None
    if args.with_counterfactual:
        cf_result = cf.analyze_decision(
            memory,
            game_id=args.game_id,
            turn=args.turn,
            decision_index=args.decision_index,
            persist=not args.no_persist,
        )
    elif args.counterfactual_json:
        cf_result = json.loads(Path(args.counterfactual_json).read_text(encoding="utf-8"))
    report = fm.classify_with_counterfactual(bundle, cf_result)
    if args.format == "json":
        print(json.dumps(report, default=str, indent=2))
    else:
        print(fm.render_markdown(report))
    return 0


def cmd_wpa(args: argparse.Namespace) -> int:
    memory = _memory(args.db)
    with memory._connect() as conn:
        report = wpa_report.build_report(
            conn,
            origin=args.origin,
            weight_version_id=args.weight_version_id,
            min_plays=args.min_plays,
        )
    if args.format == "json":
        print(json.dumps(report, default=str, indent=2))
    else:
        print(wpa_report.render_markdown(report))
    if report.get("model", {}).get("refuse_rankings"):
        return 2
    return 0


def cmd_validate_db(args: argparse.Namespace) -> int:
    memory = _memory(args.db)
    with memory._connect() as conn:
        checks = wpa_report.validate_db_readiness(conn)
    if args.format == "json":
        print(json.dumps(checks, indent=2))
    else:
        print("# Self-play DB readiness")
        for k, v in checks.items():
            print(f"- {k}: {v}")
    return 0 if checks.get("ready_for_wpa") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ai_agent.analysis")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cf = sub.add_parser("counterfactual", help="Same-turn offline counterfactual")
    p_cf.add_argument("--db", type=Path)
    p_cf.add_argument("--game-id", required=True)
    p_cf.add_argument("--turn", type=int, required=True)
    p_cf.add_argument("--decision-index", type=int, required=True)
    p_cf.add_argument("--format", choices=("markdown", "json"), default="markdown")
    p_cf.add_argument("--no-persist", action="store_true")
    p_cf.set_defaults(func=cmd_counterfactual)

    p_fr = sub.add_parser("failure-report", help="Failure-mode classification")
    p_fr.add_argument("--db", type=Path)
    p_fr.add_argument("--game-id", required=True)
    p_fr.add_argument("--turn", type=int, required=True)
    p_fr.add_argument("--decision-index", type=int, required=True)
    p_fr.add_argument("--format", choices=("markdown", "json"), default="markdown")
    p_fr.add_argument("--with-counterfactual", action="store_true")
    p_fr.add_argument("--counterfactual-json", type=Path)
    p_fr.add_argument("--no-persist", action="store_true")
    p_fr.set_defaults(func=cmd_failure_report)

    p_wpa = sub.add_parser("wpa", help="Calibrated WPA / swing-turn report")
    p_wpa.add_argument("--db", type=Path)
    p_wpa.add_argument("--origin")
    p_wpa.add_argument("--weight-version-id", type=int)
    p_wpa.add_argument("--min-plays", type=int, default=20)
    p_wpa.add_argument("--format", choices=("markdown", "json"), default="markdown")
    p_wpa.set_defaults(func=cmd_wpa)

    p_val = sub.add_parser("validate-db", help="Check snapshots / canonical outcomes")
    p_val.add_argument("--db", type=Path)
    p_val.add_argument("--format", choices=("markdown", "json"), default="markdown")
    p_val.set_defaults(func=cmd_validate_db)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
