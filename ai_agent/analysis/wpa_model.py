"""Calibrated seat-relative win-probability model (ridge logistic + Platt)."""
from __future__ import annotations

import math
import random
from typing import Any, Optional

from ..texel_tune import _sigmoid, fit_logistic

FEATURE_NAMES = [
    "score_diff",
    "board_might_diff",
    "bf_control_net",
    "hand_size_diff",
    "rune_count",
    "ready_runes",
    "turn_number",
    "turn_bucket",
    "whose_turn_ended",
    "went_first",
]

MIN_GAMES_PUBLISH = 150
MIN_GAMES_STABLE = 200
TURN_BUCKET_SIZE = 3


def turn_bucket(turn: int) -> int:
    return max(0, int(turn)) // TURN_BUCKET_SIZE


def extract_features(row: dict[str, Any]) -> list[float]:
    my_score = float(row.get("my_score") or 0)
    opp_score = float(row.get("opp_score") or 0)
    hand = float(row.get("cards_in_hand") or 0)
    opp_hand = float(row.get("cards_in_hand_opp") or 0)
    turn = int(row.get("turn") or 0)
    my_pi = row.get("my_player_index")
    turn_pi = row.get("turn_player_index")
    first_pi = row.get("first_player_index")
    whose = 1.0 if my_pi is not None and turn_pi is not None and int(my_pi) == int(turn_pi) else 0.0
    went_first = 1.0 if my_pi is not None and first_pi is not None and int(my_pi) == int(first_pi) else 0.0
    return [
        my_score - opp_score,
        float(row.get("board_might_diff") or 0),
        float(row.get("bf_control_net") or 0),
        hand - opp_hand,
        float(row.get("my_rune_count") or 0),
        float(row.get("my_ready_rune_count") or 0),
        float(turn),
        float(turn_bucket(turn)),
        whose,
        went_first,
    ]


def label_from_winner(row: dict[str, Any]) -> Optional[float]:
    winner = row.get("winner_index")
    my_pi = row.get("my_player_index")
    if winner is None or my_pi is None:
        return None
    try:
        return 1.0 if int(winner) == int(my_pi) else 0.0
    except (TypeError, ValueError):
        return None


def chronological_game_splits(
    game_ids: list[str],
    *,
    train_frac: float = 0.70,
    calib_frac: float = 0.15,
    seed: int = 0,
) -> dict[str, set[str]]:
    """Split unique game_ids in chronological order (already sorted). Both seats stay together."""
    ids = list(dict.fromkeys(game_ids))
    n = len(ids)
    n_train = int(n * train_frac)
    n_calib = int(n * calib_frac)
    # Keep deterministic; seed reserved for future jitter but order is chronological.
    _ = seed
    train = set(ids[:n_train])
    calib = set(ids[n_train:n_train + n_calib])
    test = set(ids[n_train + n_calib:])
    return {"train": train, "calibration": calib, "test": test}


def predict_logit(x: list[float], fit: dict) -> float:
    mean = fit["mean"]
    std = fit["std"]
    w = fit["w_std"]
    b = fit["b"]
    z = b
    for j, val in enumerate(x):
        if std[j] > 1e-12:
            z += w[j] * ((val - mean[j]) / std[j])
    return z


def predict_proba(x: list[float], fit: dict, *, platt: Optional[dict] = None) -> float:
    z = predict_logit(x, fit)
    p = _sigmoid(z)
    if platt:
        # Platt: p' = sigmoid(A * f + B) where f is the uncalibrated logit.
        p = _sigmoid(platt["a"] * z + platt["b"])
    return min(max(p, 1e-12), 1.0 - 1e-12)


def fit_platt(scores: list[float], labels: list[float], *, epochs: int = 800, lr: float = 0.1) -> dict:
    """Fit P = sigmoid(a * logit + b) on a held-out calibration split."""
    a = 1.0
    b = 0.0
    n = len(scores)
    if n == 0:
        return {"a": 1.0, "b": 0.0}
    for _ in range(epochs):
        ga = 0.0
        gb = 0.0
        for z, y in zip(scores, labels):
            p = _sigmoid(a * z + b)
            err = p - y
            ga += err * z
            gb += err
        inv = 1.0 / n
        a -= lr * ga * inv
        b -= lr * gb * inv
    return {"a": a, "b": b}


def brier_score(probs: list[float], labels: list[float]) -> float:
    if not probs:
        return float("nan")
    return sum((p - y) ** 2 for p, y in zip(probs, labels)) / len(probs)


def roc_auc(probs: list[float], labels: list[float]) -> float:
    pairs = sorted(zip(probs, labels), key=lambda t: t[0])
    n_pos = sum(1 for _, y in pairs if y >= 0.5)
    n_neg = len(pairs) - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    rank_sum = 0.0
    for i, (_, y) in enumerate(pairs, start=1):
        if y >= 0.5:
            rank_sum += i
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def reliability_bins(probs: list[float], labels: list[float], *, n_bins: int = 10) -> list[dict]:
    bins = [{"n": 0, "sum_p": 0.0, "sum_y": 0.0} for _ in range(n_bins)]
    for p, y in zip(probs, labels):
        idx = min(n_bins - 1, max(0, int(p * n_bins)))
        bins[idx]["n"] += 1
        bins[idx]["sum_p"] += p
        bins[idx]["sum_y"] += y
    out = []
    for i, b in enumerate(bins):
        n = b["n"]
        out.append({
            "bin": i,
            "lo": i / n_bins,
            "hi": (i + 1) / n_bins,
            "n": n,
            "avg_pred": (b["sum_p"] / n) if n else None,
            "avg_label": (b["sum_y"] / n) if n else None,
        })
    return out


def expected_calibration_error(bins: list[dict]) -> float:
    total = sum(int(b["n"]) for b in bins)
    if total == 0:
        return float("nan")
    ece = 0.0
    for b in bins:
        n = int(b["n"])
        if n == 0 or b["avg_pred"] is None or b["avg_label"] is None:
            continue
        ece += (n / total) * abs(b["avg_pred"] - b["avg_label"])
    return ece


def constant_baseline_brier(labels: list[float]) -> float:
    if not labels:
        return float("nan")
    p = sum(labels) / len(labels)
    return sum((p - y) ** 2 for y in labels) / len(labels)


def log_loss_probs(probs: list[float], labels: list[float]) -> float:
    if not probs:
        return float("nan")
    total = 0.0
    eps = 1e-12
    for p, y in zip(probs, labels):
        p = min(max(p, eps), 1.0 - eps)
        total += -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
    return total / len(probs)


def fit_wpa_model(
    rows: list[dict[str, Any]],
    *,
    l2: float = 1.0,
    epochs: int = 2000,
    seed: int = 0,
) -> dict[str, Any]:
    """Fit ridge logistic on train, Platt on calibration, evaluate on test.

    ``rows`` must already be filtered (origin / weight_version) and include
    ``split`` in {train, calibration, test} plus feature fields and ``winner_index``.
    """
    splits = {"train": [], "calibration": [], "test": []}
    for row in rows:
        lab = label_from_winner(row)
        if lab is None:
            continue
        x = extract_features(row)
        splits.setdefault(row.get("split", "train"), []).append((x, lab, row))

    train = splits.get("train") or []
    calib = splits.get("calibration") or []
    test = splits.get("test") or []
    if not train:
        return {"ok": False, "error": "no_train_rows"}

    X = [t[0] for t in train]
    y = [t[1] for t in train]
    fit = fit_logistic(X, y, l2=l2, epochs=epochs, seed=seed)
    fit["feature_names"] = list(FEATURE_NAMES)

    calib_logits = [predict_logit(t[0], fit) for t in calib]
    calib_y = [t[1] for t in calib]
    platt = fit_platt(calib_logits, calib_y) if calib else {"a": 1.0, "b": 0.0}

    def _eval(split_rows: list) -> dict:
        if not split_rows:
            return {}
        probs = [predict_proba(t[0], fit, platt=platt) for t in split_rows]
        labels = [t[1] for t in split_rows]
        bins = reliability_bins(probs, labels)
        return {
            "n": len(split_rows),
            "brier": brier_score(probs, labels),
            "log_loss": log_loss_probs(probs, labels),
            "roc_auc": roc_auc(probs, labels),
            "ece": expected_calibration_error(bins),
            "baseline_brier": constant_baseline_brier(labels),
            "reliability_bins": bins,
            "base_rate": sum(labels) / len(labels),
        }

    test_metrics = _eval(test)
    n_games = len({t[2].get("game_id") for t in train + calib + test})
    publishable = n_games >= MIN_GAMES_PUBLISH
    provisional = n_games < MIN_GAMES_STABLE
    return {
        "ok": True,
        "fit": {k: fit[k] for k in ("w_std", "b", "mean", "std", "feature_names")},
        "platt": platt,
        "train": _eval(train),
        "calibration": _eval(calib),
        "test": test_metrics,
        "n_games": n_games,
        "publishable": publishable,
        "provisional": provisional,
        "refuse_rankings": not publishable,
    }


def predict_rows(rows: list[dict], model: dict) -> list[dict]:
    fit = model["fit"]
    platt = model.get("platt")
    out = []
    for row in rows:
        x = extract_features(row)
        p = predict_proba(x, fit, platt=platt)
        rec = dict(row)
        rec["p_win"] = p
        rec["label"] = label_from_winner(row)
        out.append(rec)
    return out


def bootstrap_mean_ci(
    values: list[float],
    *,
    seed: int = 0,
    n_boot: int = 400,
    alpha: float = 0.05,
) -> dict[str, float]:
    if not values:
        return {"mean": float("nan"), "lo": float("nan"), "hi": float("nan")}
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(n_boot):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo_i = max(0, int((alpha / 2.0) * n_boot))
    hi_i = min(n_boot - 1, int((1.0 - alpha / 2.0) * n_boot))
    return {
        "mean": sum(values) / n,
        "lo": means[lo_i],
        "hi": means[hi_i],
    }
