#!/usr/bin/env python3
"""Refresh Data/AI/reaction_priors.json from riftdecks.com legend stats.

Offline import only — run manually when you want updated priors for live
LineRiskProbe threat catalogs. Does not fetch during a game turn.

Usage:
    python -m ai_agent.tools.update_reaction_priors
    python -m ai_agent.tools.update_reaction_priors --legend master-yi-wuju-bladesman --dry-run
    python -m ai_agent.tools.update_reaction_priors --metagame-id 4 --date-range all
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_URL = "https://riftdecks.com"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "Data" / "AI" / "reaction_priors.json"
DEFAULT_CARDS_DIR = Path(__file__).resolve().parents[2] / "Data" / "Cards"
USER_AGENT = "rift-unbound-priors/1.0 (local AI tool; offline refresh)"
REQUEST_DELAY_S = 1.0
TOP_N = 30
GENERIC_CAP = 8
RESERVED_KEYS = frozenset({"generic_reactions", "_meta"})

CARD_STAT_BLOCK_RE = re.compile(
    r'card-stat-item[^>]*data-presence="([\d.]+)"[^>]*>(.*?)(?=card-stat-item|Understanding the Stats|$)',
    re.DOTALL | re.IGNORECASE,
)
DETAILS_SLUG_RE = re.compile(r"/cards/details-([a-z0-9-]+)")
# Match the avg-copies badge only (×3.0). Do not use ASCII "x" — it false-matches CSS like "4px 12px".
COPIES_RE = re.compile(r"×\s*([\d.]+)")
LEGEND_HREF_RE = re.compile(r'href="/legends/([a-z0-9-]+)(?:/[^"]*)?"')
MAX_AVG_COPIES = 3.0


def normalize_avg_copies(raw: float) -> float:
    return round(min(MAX_AVG_COPIES, max(0.1, raw)), 1)


def load_local_cards(cards_dir: Path) -> dict[str, dict[str, Any]]:
    cards: dict[str, dict[str, Any]] = {}
    for path in sorted(cards_dir.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            continue
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            card_id = str(entry.get("id") or entry.get("token_id") or "")
            if card_id:
                cards[card_id] = entry
    return cards


def is_action_or_reaction(card: dict[str, Any]) -> bool:
    return bool(card.get("is_action") or card.get("is_reaction"))


def parse_card_stat_items(html: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for match in CARD_STAT_BLOCK_RE.finditer(html):
        block = match.group(2)
        slug_match = DETAILS_SLUG_RE.search(block)
        if not slug_match:
            continue
        copies_match = COPIES_RE.search(block)
        avg_copies = 1.0
        if copies_match:
            avg_copies = normalize_avg_copies(float(copies_match.group(1)))
        items.append(
            {
                "slug": slug_match.group(1),
                "presence": float(match.group(1)),
                "avg_copies": avg_copies,
            }
        )
    items.sort(key=lambda row: row["presence"], reverse=True)
    return items


def discover_legend_slugs(html: str) -> list[str]:
    slugs: set[str] = set()
    for match in LEGEND_HREF_RE.finditer(html):
        slug = match.group(1)
        if slug in {"constructed"}:
            continue
        slugs.add(slug)
    return sorted(slugs)


def filter_top_action_reactions(
    items: list[dict[str, Any]],
    cards: dict[str, dict[str, Any]],
    *,
    top_n: int = TOP_N,
) -> tuple[list[dict[str, Any]], list[str]]:
    kept: list[dict[str, Any]] = []
    skipped_unknown: list[str] = []
    for row in items[:top_n]:
        slug = str(row["slug"])
        card = cards.get(slug)
        if card is None:
            skipped_unknown.append(slug)
            continue
        if not is_action_or_reaction(card):
            continue
        kept.append(
            {
                "card_id": slug,
                "play_rate": round(float(row["presence"]) / 100.0, 4),
                "avg_copies": normalize_avg_copies(float(row["avg_copies"])),
            }
        )
    return kept, skipped_unknown


def build_generic_reactions(
    legend_priors: dict[str, list[dict[str, Any]]],
    existing_generic: list[dict[str, Any]] | None = None,
    *,
    cap: int = GENERIC_CAP,
) -> list[dict[str, Any]]:
    totals: dict[str, list[float]] = {}
    copies: dict[str, list[float]] = {}
    for entries in legend_priors.values():
        for entry in entries:
            card_id = str(entry["card_id"])
            totals.setdefault(card_id, []).append(float(entry["play_rate"]))
            copies.setdefault(card_id, []).append(float(entry.get("avg_copies", 1.0)))

    ranked = sorted(
        (
            {
                "card_id": card_id,
                "play_rate": round(sum(rates) / len(rates), 4),
                "avg_copies": round(sum(copies[card_id]) / len(copies[card_id]), 1),
                "_legend_count": len(rates),
            }
            for card_id, rates in totals.items()
            if len(rates) >= 2
        ),
        key=lambda row: row["play_rate"],
        reverse=True,
    )
    if ranked:
        return [
            {k: v for k, v in row.items() if k != "_legend_count"}
            for row in ranked[:cap]
        ]

    fallback_ids = [
        str(entry.get("card_id", ""))
        for entry in (existing_generic or [])
        if str(entry.get("card_id", ""))
    ]
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for card_id in fallback_ids:
        if card_id in seen:
            continue
        seen.add(card_id)
        if card_id not in totals:
            continue
        rates = totals[card_id]
        out.append(
            {
                "card_id": card_id,
                "play_rate": round(sum(rates) / len(rates), 4),
                "avg_copies": round(sum(copies[card_id]) / len(copies[card_id]), 1),
            }
        )
    out.sort(key=lambda row: row["play_rate"], reverse=True)
    return out[:cap]


def build_stats_url(
    legend_slug: str,
    *,
    metagame_id: int,
    date_range: str | None = None,
    board: str | None = None,
) -> str:
    params: dict[str, str | int] = {"metagame_id": metagame_id}
    if date_range:
        params["date_range"] = date_range
    if board:
        params["board"] = board
    query = urllib.parse.urlencode(params)
    return f"{BASE_URL}/legends/{legend_slug}/stats?{query}"


def build_legends_url(*, metagame_id: int, date_range: str | None = None) -> str:
    params: dict[str, str | int] = {"metagame_id": metagame_id}
    if date_range:
        params["date_range"] = date_range
    query = urllib.parse.urlencode(params)
    return f"{BASE_URL}/legends?{query}"


def fetch_url(url: str, *, timeout: float = 30.0, retries: int = 1) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code < 500 or attempt >= retries:
                raise
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt >= retries:
                raise
        time.sleep(REQUEST_DELAY_S)
    if last_error:
        raise last_error
    raise RuntimeError(f"fetch failed: {url}")


def load_existing_priors(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def merge_legend_priors(
    existing: dict[str, Any],
    updated: dict[str, list[dict[str, Any]]],
    legend_slugs: list[str],
) -> dict[str, list[dict[str, Any]]]:
    merged: dict[str, list[dict[str, Any]]] = {}
    for key, value in existing.items():
        if key in RESERVED_KEYS or not isinstance(value, list):
            continue
        merged[key] = value
    for slug in legend_slugs:
        if slug in updated:
            merged[slug] = updated[slug]
    return merged


def build_payload(
    *,
    legend_slugs: list[str],
    fetch_html,
    cards: dict[str, dict[str, Any]],
    existing_generic: list[dict[str, Any]] | None,
    metagame_id: int,
    date_range: str | None,
    board: str | None,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    legend_entries: dict[str, list[dict[str, Any]]] = {}
    skipped_by_legend: dict[str, list[str]] = {}

    for slug in legend_slugs:
        url = build_stats_url(
            slug,
            metagame_id=metagame_id,
            date_range=date_range,
            board=board,
        )
        html = fetch_html(url)
        items = parse_card_stat_items(html)
        kept, skipped = filter_top_action_reactions(items, cards)
        legend_entries[slug] = kept
        if skipped:
            skipped_by_legend[slug] = skipped

    generic = build_generic_reactions(legend_entries, existing_generic)
    payload: dict[str, Any] = {"generic_reactions": generic}
    payload.update(legend_entries)
    payload["_meta"] = {
        "source": "riftdecks.com",
        "metagame_id": metagame_id,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "legend_count": len(legend_entries),
    }
    if date_range:
        payload["_meta"]["date_range"] = date_range
    if board:
        payload["_meta"]["board"] = board
    return payload, skipped_by_legend


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def collect_legend_slugs(
    *,
    requested: list[str] | None,
    discovered: list[str],
    existing: dict[str, Any],
    cards: dict[str, dict[str, Any]],
) -> list[str]:
    if requested:
        return requested
    slugs = set(discovered)
    for key in existing:
        if key not in RESERVED_KEYS:
            slugs.add(key)
    for card_id, card in cards.items():
        if card.get("card_type") == "legend":
            slugs.add(card_id)
    return sorted(slugs)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output JSON path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--cards-dir",
        type=Path,
        default=DEFAULT_CARDS_DIR,
        help=f"Local card JSON directory (default: {DEFAULT_CARDS_DIR})",
    )
    parser.add_argument(
        "--metagame-id",
        type=int,
        default=1,
        help="riftdecks metagame filter (1=Origins, 2=Spiritforged, 3=Unleashed, 4=Vendetta)",
    )
    parser.add_argument(
        "--date-range",
        default=None,
        help="Optional date range query param (omit by default; site defaults apply)",
    )
    parser.add_argument(
        "--board",
        default=None,
        choices=("main", "battlefields", "side"),
        help="Optional deck board filter (omit by default)",
    )
    parser.add_argument(
        "--legend",
        action="append",
        dest="legends",
        metavar="SLUG",
        help="Refresh only this legend (repeatable). Default: all discovered legends.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print JSON to stdout instead of writing the file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cards = load_local_cards(args.cards_dir)
    existing = load_existing_priors(args.output)
    existing_generic = existing.get("generic_reactions")
    if not isinstance(existing_generic, list):
        existing_generic = None

    legends_html = fetch_url(
        build_legends_url(metagame_id=args.metagame_id, date_range=args.date_range)
    )
    discovered = discover_legend_slugs(legends_html)
    legend_slugs = collect_legend_slugs(
        requested=args.legends,
        discovered=discovered,
        existing=existing,
        cards=cards,
    )
    if not legend_slugs:
        print("No legend slugs to refresh.", file=sys.stderr)
        return 1

    last_fetch_at = 0.0

    def fetch_html(url: str) -> str:
        nonlocal last_fetch_at
        elapsed = time.monotonic() - last_fetch_at
        if elapsed < REQUEST_DELAY_S:
            time.sleep(REQUEST_DELAY_S - elapsed)
        html = fetch_url(url)
        last_fetch_at = time.monotonic()
        return html

    updated_entries: dict[str, list[dict[str, Any]]] = {}
    skipped_by_legend: dict[str, list[str]] = {}
    for slug in legend_slugs:
        url = build_stats_url(
            slug,
            metagame_id=args.metagame_id,
            date_range=args.date_range,
            board=args.board,
        )
        print(f"Fetching {slug} …", file=sys.stderr)
        html = fetch_html(url)
        items = parse_card_stat_items(html)
        kept, skipped = filter_top_action_reactions(items, cards)
        updated_entries[slug] = kept
        if skipped:
            skipped_by_legend[slug] = skipped
        print(f"  {len(kept)} action/reaction cards ({len(items)} tiles parsed)", file=sys.stderr)

    merged_legends = merge_legend_priors(existing, updated_entries, legend_slugs)
    generic = build_generic_reactions(merged_legends, existing_generic)
    payload: dict[str, Any] = {"generic_reactions": generic}
    payload.update(merged_legends)
    payload["_meta"] = {
        "source": "riftdecks.com",
        "metagame_id": args.metagame_id,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "legend_count": len(updated_entries),
        "refreshed_legends": legend_slugs,
    }
    if args.date_range:
        payload["_meta"]["date_range"] = args.date_range
    if args.board:
        payload["_meta"]["board"] = args.board

    for slug, skipped in sorted(skipped_by_legend.items()):
        print(f"Skipped unknown cards for {slug}: {', '.join(skipped)}", file=sys.stderr)

    if args.dry_run:
        print(json.dumps(payload, indent=2))
    else:
        write_json_atomic(args.output, payload)
        print(f"Wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
