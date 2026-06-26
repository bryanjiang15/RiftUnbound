#!/usr/bin/env python3
"""Texel weight tuner (Phase 1 of the score-tuning roadmap).

Implements Texel's tuning method (chessprogramming.org/Texel%27s_Tuning_Method):
fit the linear evaluation weights so that ``sigmoid(K * eval(position))`` best
predicts the **final game outcome** of each logged position. See
``ai_agent/docs/Score_Tuning_And_Evolution.md`` §2.1 (this is build-order step 2).

Pipeline this plugs into (all already collected by self-play):

    ScoreModel.build_score_features()  -> raw feature dict
        (stored as search_decisions.chosen_features_json)
    ScoringProfile.score_with_breakdown() -> weight * feature per term
    backfill_game_outcome()  -> labels each row win/loss/draw

This script is a **proposer only**: it writes a *candidate* scoring_profile.json
(via --out) and prints a diagnosis. It never overwrites the live profile — the
win-rate / SPRT gate that actually commits weights is a later phase.

Usage:
    python ai_agent/texel_tune.py --db ai_agent/selfplay.db --out candidate_profile.json
    python ai_agent/texel_tune.py --origin self_play --min-turn 2 --lambda 1.0
    python ai_agent/texel_tune.py --dry-run        # diagnose only, no file written

Filtering mirrors feature_report.py (all combine with AND):
    --origin --selector --mode --outcome --seat --went-first
    --game-id --weight-version --turn / --min-turn / --max-turn
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = Path(__file__).parent / "agent_memory.db"
DEFAULT_PROFILE_PATH = REPO_ROOT / "Data" / "AI" / "scoring_profile.json"

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except (AttributeError, ValueError):
    pass

# ── Tunable weight → feature mapping (mirrors ScoringProfile.score_with_breakdown).
# Each tunable weight w multiplies exactly one feature value x; the eval term is
# w * x. These maps let us rebuild x from the raw build_score_features dict so we
# can regress the weights. Held FIXED in phase 1 (not regressed):
#   win_game (terminal), battlefield_weights, end_of_turn, mulligan.

# weight key (under state_weights) -> feature key in the raw feature dict.
STATE_FEATURE_MAP = {
    "score_diff": "score_diff",
    "unit_might_on_board": "unit_might_diff",
    "cards_in_hand": "cards_in_hand_self",
    "runes_available": "runes_available_diff",
    "reactive_potential": "reactive_potential",
    "unusable_runes": "unusable_runes",
}
# weight key (under action_weights) -> feature key in the raw feature dict.
ACTION_FEATURE_MAP = {
    "card_played": "cards_played",
    "unit_moved": "units_moved",
    "card_discarded": "cards_discarded",
    "enemy_unit_killed": "enemy_units_killed",
    "own_unit_lost": "own_units_lost",
    "battlefield_conquered": "battlefields_conquered",
    "point_scored": "points_scored",
    "card_drawn": "cards_drawn",
    "power_used": "power_used",
}
# state_weights.battlefield_control is special: its feature value is a derived
# scalar over the bf-control dict weighted by battlefield_weights (held fixed).

_OUTCOME_LABEL = {"win": 1.0, "loss": 0.0, "draw": 0.5}


# ── Term extraction ──────────────────────────────────────────────────────────


def _battlefield_control_value(features: dict, bf_weights: dict) -> float:
    """Mirror of ScoringProfile._battlefield_control: signed weighted bf control.

    +bf_weight per battlefield the AI controls, -bf_weight per opponent-controlled
    one. battlefield_weights are held fixed in phase 1, so this collapses to a
    single scalar feature multiplied by the tunable battlefield_control weight.
    """
    ai_index = int(features.get("ai_index", 0))
    total = 0.0
    controls = features.get("bf", {}) or {}
    for bf_id, ctrl in controls.items():
        weight = float(bf_weights.get(str(bf_id), 1.0))
        ctrl = int(ctrl)
        if ctrl == ai_index:
            total += weight
        elif ctrl >= 0:
            total -= weight
    return total


def extract_terms(features: dict, profile: dict) -> "dict[tuple[str, str], float]":
    """Raw feature dict -> {(group, weight_key): feature_value} for tunable weights.

    The returned values are exactly the x in ``term = weight * x`` for every
    weight Texel will regress. Keyword weights expand per-keyword from keyword_net.
    """
    bf_weights = profile.get("battlefield_weights", {}) or {}
    keyword_net = features.get("keyword_net", {}) or {}
    out: dict[tuple[str, str], float] = {}

    for wkey, fkey in STATE_FEATURE_MAP.items():
        out[("state_weights", wkey)] = float(features.get(fkey, 0) or 0)
    out[("state_weights", "battlefield_control")] = _battlefield_control_value(
        features, bf_weights
    )
    for wkey, fkey in ACTION_FEATURE_MAP.items():
        out[("action_weights", wkey)] = float(features.get(fkey, 0) or 0)
    for kw in profile.get("keyword_weights", {}) or {}:
        out[("keyword_weights", kw)] = float(keyword_net.get(kw, 0) or 0)
    return out


def is_terminal(features: dict) -> bool:
    """Terminal positions (game already decided at the leaf) are excluded: the
    dominating win_game term would otherwise swamp the shaping signal (doc §2.1).
    """
    return bool(features.get("game_over", False))


# ── Dataset loading ──────────────────────────────────────────────────────────


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        sys.exit(f"Database not found: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _where_clause(filters: dict) -> "tuple[str, list]":
    where = [
        "chosen_features_json IS NOT NULL",
        "game_outcome IS NOT NULL",
    ]
    params: list = []
    for col, key in (
        ("origin", "origin"),
        ("selector_source", "selector"),
        ("mode", "mode"),
        ("game_outcome", "outcome"),
        ("my_player_index", "seat"),
        ("went_first", "went_first"),
        ("game_id", "game_id"),
        ("weight_version_id", "weight_version"),
    ):
        val = filters.get(key)
        if val is not None:
            where.append(f"{col} = ?")
            params.append(val)
    if filters.get("min_turn") is not None:
        where.append("turn >= ?")
        params.append(filters["min_turn"])
    if filters.get("max_turn") is not None:
        where.append("turn <= ?")
        params.append(filters["max_turn"])
    return " AND ".join(where), params


def load_dataset(conn: sqlite3.Connection, *, profile: dict, filters: dict) -> dict:
    """Return {"keys": ordered tunable weight keys, "X": rows of feature vectors,
    "y": labels, "skipped_terminal": n, "total": n}.

    Each row of X is aligned to "keys" (list of (group, key) tuples). Labels map
    win/loss/draw -> 1/0/0.5.
    """
    where_sql, params = _where_clause(filters)
    sql = (
        "SELECT chosen_features_json, game_outcome FROM search_decisions WHERE "
        + where_sql
    )
    rows = conn.execute(sql, params).fetchall()

    keys = ordered_weight_keys(profile)
    X: list[list[float]] = []
    y: list[float] = []
    skipped_terminal = 0
    skipped_bad = 0
    for r in rows:
        try:
            feats = json.loads(r["chosen_features_json"])
        except (TypeError, json.JSONDecodeError):
            skipped_bad += 1
            continue
        if not isinstance(feats, dict):
            skipped_bad += 1
            continue
        if is_terminal(feats):
            skipped_terminal += 1
            continue
        label = _OUTCOME_LABEL.get(str(r["game_outcome"]).lower())
        if label is None:
            skipped_bad += 1
            continue
        terms = extract_terms(feats, profile)
        X.append([terms.get(k, 0.0) for k in keys])
        y.append(label)
    return {
        "keys": keys,
        "X": X,
        "y": y,
        "skipped_terminal": skipped_terminal,
        "skipped_bad": skipped_bad,
        "total": len(rows),
    }


def ordered_weight_keys(profile: dict) -> "list[tuple[str, str]]":
    """Stable ordering of the tunable (group, key) weights present in the profile."""
    keys: list[tuple[str, str]] = []
    for wkey in STATE_FEATURE_MAP:
        keys.append(("state_weights", wkey))
    keys.append(("state_weights", "battlefield_control"))
    for wkey in ACTION_FEATURE_MAP:
        keys.append(("action_weights", wkey))
    for kw in profile.get("keyword_weights", {}) or {}:
        keys.append(("keyword_weights", kw))
    return keys


def current_weight(profile: dict, key: "tuple[str, str]") -> float:
    group, wkey = key
    return float((profile.get(group, {}) or {}).get(wkey, 0.0))


# ── Logistic fit (Texel) ─────────────────────────────────────────────────────


def _sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _standardize(X: "list[list[float]]") -> "tuple[list[float], list[float]]":
    """Per-column mean / std. Zero-variance columns get std=0 (skipped in fit)."""
    n = len(X)
    m = len(X[0]) if n else 0
    mean = [0.0] * m
    for row in X:
        for j in range(m):
            mean[j] += row[j]
    mean = [v / n for v in mean] if n else mean
    var = [0.0] * m
    for row in X:
        for j in range(m):
            d = row[j] - mean[j]
            var[j] += d * d
    std = [math.sqrt(v / n) if n else 0.0 for v in var]
    return mean, std


def fit_logistic(
    X: "list[list[float]]",
    y: "list[float]",
    *,
    k: float = 1.0,
    l2: float = 1.0,
    lr: float = 0.5,
    epochs: int = 4000,
    seed: int = 0,
) -> dict:
    """Fit standardized logistic weights via batch gradient descent on log-loss.

    Returns standardized weights w_std (+ intercept b), the per-column mean/std,
    and the train log-loss. Features are standardized internally so L2 (ridge,
    required for the correlated features in this game) is fair across columns;
    callers convert back to raw-feature weight scale with ``raw_weights``.
    """
    n = len(X)
    m = len(X[0]) if n else 0
    if n == 0 or m == 0:
        return {"w_std": [0.0] * m, "b": 0.0, "mean": [0.0] * m,
                "std": [0.0] * m, "loss": float("nan")}
    random.seed(seed)
    mean, std = _standardize(X)
    # Standardized design matrix (zero-variance columns -> all zeros).
    Z = [[((X[i][j] - mean[j]) / std[j]) if std[j] > 1e-12 else 0.0
          for j in range(m)] for i in range(n)]

    w = [0.0] * m
    b = 0.0
    for _ in range(epochs):
        gw = [0.0] * m
        gb = 0.0
        for i in range(n):
            z = b
            zi = Z[i]
            for j in range(m):
                z += w[j] * zi[j]
            p = _sigmoid(k * z)
            err = p - y[i]
            ke = k * err
            for j in range(m):
                gw[j] += ke * zi[j]
            gb += ke
        inv = 1.0 / n
        for j in range(m):
            grad = gw[j] * inv + l2 * w[j] * inv
            w[j] -= lr * grad
        b -= lr * gb * inv

    loss = log_loss(Z, y, w, b, k)
    return {"w_std": w, "b": b, "mean": mean, "std": std, "loss": loss}


def log_loss(Z: "list[list[float]]", y: "list[float]", w: "list[float]",
             b: float, k: float) -> float:
    n = len(Z)
    if n == 0:
        return float("nan")
    total = 0.0
    eps = 1e-12
    for i in range(n):
        z = b + sum(w[j] * Z[i][j] for j in range(len(w)))
        p = min(max(_sigmoid(k * z), eps), 1.0 - eps)
        total += -(y[i] * math.log(p) + (1.0 - y[i]) * math.log(1.0 - p))
    return total / n


def accuracy(Z: "list[list[float]]", y: "list[float]", w: "list[float]",
             b: float, k: float) -> float:
    n = len(Z)
    if n == 0:
        return float("nan")
    correct = 0
    for i in range(n):
        z = b + sum(w[j] * Z[i][j] for j in range(len(w)))
        p = _sigmoid(k * z)
        pred = 1.0 if p >= 0.5 else 0.0
        label = 1.0 if y[i] >= 0.5 else 0.0  # draws (0.5) count as the positive side
        if pred == label:
            correct += 1
    return correct / n


def raw_weights(fit: dict, keys: "list[tuple[str, str]]") -> "dict[tuple[str, str], Optional[float]]":
    """Convert standardized weights back to raw-feature scale: w_raw = w_std/std.

    Zero-variance columns (std≈0) carry no signal in this dataset and return None
    (caller keeps the current weight for them).
    """
    w_std = fit["w_std"]
    std = fit["std"]
    out: dict[tuple[str, str], Optional[float]] = {}
    for j, key in enumerate(keys):
        if std[j] > 1e-12:
            out[key] = w_std[j] / std[j]
        else:
            out[key] = None
    return out


# ── Profile output + diagnosis ───────────────────────────────────────────────


def build_candidate_profile(profile: dict, new_raw: "dict[tuple[str, str], Optional[float]]") -> dict:
    """Copy the live profile and overwrite only the regressed scalar weights."""
    cand = json.loads(json.dumps(profile))  # deep copy
    for (group, wkey), val in new_raw.items():
        if val is None:
            continue
        cand.setdefault(group, {})[wkey] = round(val, 4)
    return cand


def diagnose(profile: dict, new_raw: "dict[tuple[str, str], Optional[float]]",
             keys: "list[tuple[str, str]]") -> "list[dict]":
    """Per-weight old→new diagnosis: dead (≈0) and sign-flip detection (doc §2.1)."""
    rows = []
    for key in keys:
        old = current_weight(profile, key)
        new = new_raw.get(key)
        if new is None:
            status = "no-signal"  # zero-variance in this dataset; weight kept
            new_disp = old
        else:
            new_disp = new
            dead = abs(new) < 1e-3
            flip = (old > 0 > new) or (old < 0 < new)
            if dead:
                status = "dead"
            elif flip:
                status = "sign-flip"
            else:
                status = "ok"
        rows.append({
            "group": key[0],
            "key": key[1],
            "old": old,
            "new": new_disp,
            "status": status,
        })
    return rows


def _load_profile(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"Could not load profile {path}: {exc}")


def render_report(ds: dict, fit: dict, diag: "list[dict]", *, val_loss: float,
                  val_acc: float, k: float, l2: float) -> str:
    out: list[str] = []
    out.append("")
    out.append("  Texel weight tuning — candidate proposal")
    n = len(ds["y"])
    pos = sum(1 for v in ds["y"] if v >= 0.75)
    neg = sum(1 for v in ds["y"] if v <= 0.25)
    drw = n - pos - neg
    out.append(f"    positions used : {n}  (win {pos} / loss {neg} / draw {drw})")
    out.append(f"    excluded       : {ds['skipped_terminal']} terminal, "
               f"{ds['skipped_bad']} unparseable  (of {ds['total']} rows)")
    out.append(f"    hyperparams    : K={k}  L2(ridge)={l2}")
    out.append(f"    train log-loss : {fit['loss']:.4f}")
    if not math.isnan(val_loss):
        out.append(f"    val   log-loss : {val_loss:.4f}   val acc: {val_acc:.3f}")
    out.append("")
    name_w = max(len("weight"), max(len(f"{d['group']}.{d['key']}") for d in diag))
    out.append(f"  {'weight':<{name_w}}  {'old':>9}  {'new':>9}  status")
    out.append("  " + "-" * (name_w + 32))
    flips = []
    dead = []
    for d in diag:
        name = f"{d['group']}.{d['key']}"
        tag = d["status"]
        out.append(f"  {name:<{name_w}}  {d['old']:>9.3f}  {d['new']:>9.3f}  {tag}")
        if tag == "sign-flip":
            flips.append(name)
        elif tag == "dead":
            dead.append(name)
    out.append("")
    out.append("  Diagnosis")
    out.append(f"    sign-flips (miscalibrated): {', '.join(flips) if flips else 'none'}")
    out.append(f"    dead weights (≈0 impact)  : {', '.join(dead) if dead else 'none'}")
    out.append("")
    return "\n".join(out)


# ── CLI ──────────────────────────────────────────────────────────────────────


def _split(X: list, y: list, val_frac: float, seed: int):
    idx = list(range(len(X)))
    random.Random(seed).shuffle(idx)
    n_val = int(len(idx) * val_frac)
    val_idx = set(idx[:n_val])
    Xtr, ytr, Xva, yva = [], [], [], []
    for i in range(len(X)):
        if i in val_idx:
            Xva.append(X[i]); yva.append(y[i])
        else:
            Xtr.append(X[i]); ytr.append(y[i])
    return Xtr, ytr, Xva, yva


def main(argv: "list[str] | None" = None) -> int:
    p = argparse.ArgumentParser(description="Texel weight tuner (Phase 1 proposer).")
    p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH,
                   help=f"SQLite DB path (default: {DEFAULT_DB_PATH})")
    p.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH,
                   help="Base scoring profile to start from (default: live profile)")
    p.add_argument("--out", type=Path, default=None,
                   help="Write candidate profile JSON here (omit / --dry-run to skip)")
    p.add_argument("--dry-run", action="store_true", help="Diagnose only; write nothing")
    # Hyperparameters.
    p.add_argument("--k", type=float, default=1.0, help="Sigmoid scaling K (default 1.0)")
    p.add_argument("--lambda", type=float, default=1.0, dest="l2",
                   help="L2 / ridge strength (default 1.0; required for correlated feats)")
    p.add_argument("--lr", type=float, default=0.5, help="Gradient-descent learning rate")
    p.add_argument("--epochs", type=int, default=4000, help="Gradient-descent epochs")
    p.add_argument("--val-frac", type=float, default=0.2, help="Held-out validation fraction")
    p.add_argument("--seed", type=int, default=0, help="RNG seed (split + init)")
    # Filters (mirror feature_report.py).
    p.add_argument("--origin")
    p.add_argument("--selector")
    p.add_argument("--mode")
    p.add_argument("--outcome")
    p.add_argument("--seat", type=int)
    p.add_argument("--went-first", type=int, choices=[0, 1], dest="went_first")
    p.add_argument("--game-id", dest="game_id")
    p.add_argument("--weight-version", type=int, dest="weight_version")
    p.add_argument("--min-turn", type=int, dest="min_turn")
    p.add_argument("--max-turn", type=int, dest="max_turn")
    p.add_argument("--turn", type=int)
    args = p.parse_args(argv)

    min_turn, max_turn = args.min_turn, args.max_turn
    if args.turn is not None:
        min_turn = max_turn = args.turn
    filters = {
        "origin": args.origin, "selector": args.selector, "mode": args.mode,
        "outcome": args.outcome, "seat": args.seat, "went_first": args.went_first,
        "game_id": args.game_id, "weight_version": args.weight_version,
        "min_turn": min_turn, "max_turn": max_turn,
    }

    profile = _load_profile(args.profile)
    conn = _connect(args.db)
    try:
        ds = load_dataset(conn, profile=profile, filters=filters)
    finally:
        conn.close()

    if not ds["X"]:
        sys.exit("No usable (non-terminal, labeled) positions matched the filters.")

    Xtr, ytr, Xva, yva = _split(ds["X"], ds["y"], args.val_frac, args.seed)
    fit = fit_logistic(Xtr, ytr, k=args.k, l2=args.l2, lr=args.lr,
                       epochs=args.epochs, seed=args.seed)

    # Validation metrics (standardize val with TRAIN mean/std).
    val_loss = float("nan")
    val_acc = float("nan")
    if Xva:
        std, mean = fit["std"], fit["mean"]
        Zva = [[((Xva[i][j] - mean[j]) / std[j]) if std[j] > 1e-12 else 0.0
                for j in range(len(mean))] for i in range(len(Xva))]
        val_loss = log_loss(Zva, yva, fit["w_std"], fit["b"], args.k)
        val_acc = accuracy(Zva, yva, fit["w_std"], fit["b"], args.k)

    new_raw = raw_weights(fit, ds["keys"])
    diag = diagnose(profile, new_raw, ds["keys"])
    print(render_report(ds, fit, diag, val_loss=val_loss, val_acc=val_acc,
                        k=args.k, l2=args.l2))

    if args.out and not args.dry_run:
        cand = build_candidate_profile(profile, new_raw)
        args.out.write_text(json.dumps(cand, indent=2) + "\n", encoding="utf-8")
        print(f"  Candidate profile written: {args.out}")
        print("  (proposer only — validate with self-play win-rate before committing)\n")
    elif not args.dry_run:
        print("  No --out given; ran as diagnosis only (use --out PATH to save).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
