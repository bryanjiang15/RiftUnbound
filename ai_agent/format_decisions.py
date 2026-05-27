#!/usr/bin/env python3
"""
Riftbound AI Agent — Decision Log Viewer

Reads agent_decisions.log (plain text, written by the live service) and
prints it with optional ANSI colour highlighting and filtering.

The log file is already human-readable — you can open it in any text editor
or follow it live with:

    tail -f ai_agent/agent_decisions.log

This script adds colour and filtering on top of that.

Usage:
  python -m ai_agent.format_decisions              # print full log with colour
  python -m ai_agent.format_decisions --turn 3     # only decisions from turn 3
  python -m ai_agent.format_decisions --type main_phase
  python -m ai_agent.format_decisions --no-color   # plain text (pipe-friendly)
  python -m ai_agent.format_decisions --follow      # live tail with colour
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

# ── ANSI colour helpers ───────────────────────────────────────────────────────

_USE_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


BOLD    = lambda t: _c("1",  t)
DIM     = lambda t: _c("2",  t)
CYAN    = lambda t: _c("96", t)
YELLOW  = lambda t: _c("93", t)
GREEN   = lambda t: _c("92", t)
MAGENTA = lambda t: _c("95", t)
RED     = lambda t: _c("91", t)
BLUE    = lambda t: _c("94", t)

_TYPE_COLOR = {
    "mulligan":          MAGENTA,
    "main_phase":        GREEN,
    "showdown_focus":    YELLOW,
    "chain_reaction":    CYAN,
    "combat_assignment": RED,
    "pending_choice":    BLUE,
    "Mulligan":          MAGENTA,
    "Main Phase":        GREEN,
    "Showdown":          YELLOW,
    "Chain Reaction":    CYAN,
    "Combat Damage":     RED,
    "Pending Choice":    BLUE,
}

LOG_FILE = Path(__file__).parent / "agent_decisions.log"

# Pattern that matches the header line of each decision block:
# "Turn 1  #0  Main Phase  [high]  2026-05-17T04:37:18Z"
_HEADER_RE = re.compile(
    r"^Turn\s+(\d+)\s+#(\d+)\s+([\w ]+?)(?:\s+\[(\w+)\])?\s+(\d{4}-\d{2}T\S+)$"
)
_ACTION_RE  = re.compile(r"^\s+Action:\s+(.+)$")
_CMD_RE     = re.compile(r"^\s+Command:\s+(.+)$")
_DIVIDER_RE = re.compile(r"^─+$")


def _colorize_block(block: str) -> str:
    """Add ANSI colour to an already-formatted decision block."""
    if not _USE_COLOR:
        return block

    out_lines = []
    for line in block.splitlines():
        # Divider
        if _DIVIDER_RE.match(line):
            out_lines.append(DIM(line))
            continue

        # Header line: Turn N  #N  <Type>  [conf]  <ts>
        m = _HEADER_RE.match(line)
        if m:
            turn, idx, type_label, conf, ts = m.groups()
            color_fn = _TYPE_COLOR.get(type_label.strip(), DIM)
            conf_str = f"  {DIM('[' + conf + ']')}" if conf else ""
            out_lines.append(
                f"{BOLD('Turn ' + turn)}  {DIM('#' + idx)}"
                f"  {color_fn(BOLD(type_label.strip()))}"
                f"{conf_str}  {DIM(ts)}"
            )
            continue

        # Action line
        m = _ACTION_RE.match(line)
        if m:
            out_lines.append(f"  {YELLOW('Action:   ')} {BOLD(m.group(1))}")
            continue

        # Command line
        m = _CMD_RE.match(line)
        if m:
            out_lines.append(f"  {YELLOW('Command:  ')} {CYAN(m.group(1))}")
            continue

        # Section labels
        if line.strip() in ("Reasoning:", "Alternatives:"):
            out_lines.append(f"  {YELLOW(line.strip())}")
            continue

        out_lines.append(line)

    return "\n".join(out_lines)


def _parse_turn(block: str) -> int | None:
    """Extract turn number from a block, or None if not found."""
    for line in block.splitlines():
        m = _HEADER_RE.match(line)
        if m:
            return int(m.group(1))
    return None


def _parse_type(block: str) -> str | None:
    """Extract decision type label from a block, or None."""
    for line in block.splitlines():
        m = _HEADER_RE.match(line)
        if m:
            return m.group(3).strip().lower().replace(" ", "_")
    return None


def _split_blocks(text: str) -> list[str]:
    """Split the log text into individual decision blocks."""
    # Blocks start with the divider line ────...
    raw = re.split(r"(?=^─{10,})", text, flags=re.MULTILINE)
    blocks = []
    for chunk in raw:
        chunk = chunk.strip()
        if chunk and _DIVIDER_RE.match(chunk.splitlines()[0] if chunk else ""):
            blocks.append(chunk)
    return blocks


def _print_header(log_path: Path) -> None:
    content = log_path.read_text(encoding="utf-8")
    # The file header is everything before the first divider
    preamble = content.split("─" * 10)[0].strip()
    if preamble:
        print(BOLD(preamble) if _USE_COLOR else preamble)
        print()


# ── Commands ──────────────────────────────────────────────────────────────────


def cmd_print(log_path: Path, turn_filter: int | None, type_filter: str | None) -> None:
    if not log_path.exists():
        print(f"Log file not found: {log_path}", file=sys.stderr)
        sys.exit(1)

    text = log_path.read_text(encoding="utf-8")
    blocks = _split_blocks(text)

    if not blocks:
        _print_header(log_path)
        print(DIM("  (no decisions logged yet — start a game)") if _USE_COLOR
              else "  (no decisions logged yet — start a game)")
        return

    # Apply filters
    if turn_filter is not None:
        blocks = [b for b in blocks if _parse_turn(b) == turn_filter]
    if type_filter:
        blocks = [b for b in blocks if _parse_type(b) == type_filter]

    _print_header(log_path)

    if not blocks:
        print("  (no decisions match the given filters)")
        return

    for block in blocks:
        print(_colorize_block(block))
        print()

    # Summary
    all_blocks = _split_blocks(text)
    turns_all = [_parse_turn(b) for b in all_blocks if _parse_turn(b) is not None]
    type_counts: dict[str, int] = {}
    for b in all_blocks:
        t = _parse_type(b)
        if t:
            type_counts[t] = type_counts.get(t, 0) + 1

    divider = DIM("· " * 36) if _USE_COLOR else "· " * 36
    print(divider)
    shown = len(blocks)
    total = len(all_blocks)
    filtered_note = f" (showing {shown}/{total})" if shown != total else ""
    print(BOLD(f"  {total} decisions{filtered_note}") if _USE_COLOR
          else f"  {total} decisions{filtered_note}")
    if turns_all:
        print(f"  Turns: {min(turns_all)} – {max(turns_all)}")
    for dtype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        label = dtype.replace("_", " ").title()
        color_fn = _TYPE_COLOR.get(label, DIM)
        bar = "█" * count
        line = f"    {label:<20}  {count:3d}  {bar}"
        print(color_fn(line) if _USE_COLOR else line)
    print(divider)


def cmd_follow(log_path: Path) -> None:
    """Tail the log file and print new blocks as they arrive."""
    if not log_path.exists():
        log_path.touch()

    print(DIM(f"Following {log_path.name} — press Ctrl+C to stop") if _USE_COLOR
          else f"Following {log_path.name} — press Ctrl+C to stop")
    print()

    seen_size = 0
    buffer = ""
    try:
        while True:
            current_size = log_path.stat().st_size
            if current_size < seen_size:
                # File was cleared (server restarted)
                print("\n" + BOLD("── server restarted, log cleared ──") + "\n"
                      if _USE_COLOR else "\n── server restarted, log cleared ──\n")
                buffer = ""
                seen_size = 0

            if current_size > seen_size:
                with log_path.open(encoding="utf-8") as fh:
                    fh.seek(seen_size)
                    new_text = fh.read()
                seen_size = current_size
                buffer += new_text

                # Print complete blocks (end with double newline)
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    block = block.strip()
                    if block and _DIVIDER_RE.match(block.splitlines()[0]):
                        print(_colorize_block(block))
                        print()

            time.sleep(0.5)
    except KeyboardInterrupt:
        print()


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="View the Riftbound agent decision log with colour and filtering.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "file", nargs="?", default=None,
        help=f"Log file to read (default: {LOG_FILE.name})",
    )
    parser.add_argument(
        "--turn", type=int, default=None,
        help="Only show decisions from this turn number",
    )
    parser.add_argument(
        "--type", dest="dtype", default=None,
        help="Filter by decision type: mulligan, main_phase, showdown_focus, "
             "chain_reaction, combat_assignment, pending_choice",
    )
    parser.add_argument(
        "--follow", "-f", action="store_true",
        help="Live-tail the log file (like tail -f, but with colour)",
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="Disable ANSI colour output",
    )
    args = parser.parse_args()

    global _USE_COLOR
    if args.no_color:
        _USE_COLOR = False

    log_path = Path(args.file) if args.file else LOG_FILE

    if args.follow:
        cmd_follow(log_path)
    else:
        cmd_print(log_path, turn_filter=args.turn, type_filter=args.dtype)


if __name__ == "__main__":
    main()
