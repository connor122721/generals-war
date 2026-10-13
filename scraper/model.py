"""Wins Above Replacement for battlefield commanders.

For every battle we estimate the probability that an *average* ("replacement")
commander would have won from the same position, using only the relative size
of the two forces:

    P(side 1 wins) = 1 / (1 + exp(-b * log(strength1 / strength2)))

``b`` is fitted by maximum likelihood on all battles that have both strengths
and a known outcome (draws count as half a win). When either strength is
missing the replacement probability is 0.5.

A commander's WAR for one battle is   outcome - P(replacement wins)
where outcome is 1 for a win, 0.5 for a draw and 0 for a loss. Career WAR is
the sum over battles. "Shared" WAR splits each side's credit equally among its
listed commanders.
"""
from __future__ import annotations

import math

CLIP = math.log(20)  # cap force ratios at 20:1 so a few absurd values can't dominate


def ratio_feature(s1: float | None, s2: float | None) -> float | None:
    if not s1 or not s2 or s1 <= 0 or s2 <= 0:
        return None
    return max(-CLIP, min(CLIP, math.log(s1 / s2)))


def outcome_side1(winner: int | None) -> float | None:
    return {0: 1.0, 1: 0.0, -1: 0.5}.get(winner)


def fit(battles: list[dict]) -> dict:
    """Fit the one-parameter logistic model. Returns {"b", "n", "se", "calibration"}."""
    xs, ys = [], []
    for b in battles:
        x = ratio_feature(b.get("s1"), b.get("s2"))
        y = outcome_side1(b.get("winner"))
        if x is None or y is None:
            continue
        # Use both orientations so the fit is symmetric (side numbering is arbitrary).
        xs += [x, -x]
        ys += [y, 1 - y]
    coef = 0.0
    hess = 0.0
    for _ in range(50):
        grad = hess = 0.0
        for x, y in zip(xs, ys):
            p = 1 / (1 + math.exp(-coef * x))
            grad += (y - p) * x
            hess += p * (1 - p) * x * x
        if hess == 0:
            break
        step = grad / hess
        coef += step
        if abs(step) < 1e-9:
            break
    se = math.sqrt(2 / hess) if hess else None  # x2: each battle was counted twice
    # Calibration: observed win rate of the larger side, by force-ratio bin
    bins = [(1, 1.25), (1.25, 1.5), (1.5, 2), (2, 3), (3, 5), (5, 20.01)]
    calib = []
    for lo, hi in bins:
        sel = [(x, y) for x, y in zip(xs, ys) if math.log(lo) <= x < math.log(hi) and x > 0 or (lo == 1 and x == 0)]
        if not sel:
            continue
        obs = sum(y for _, y in sel) / len(sel)
        mid = math.sqrt(lo * min(hi, 20))
        calib.append({"ratio": f"{lo:g}–{min(hi, 20):g}×", "n": len(sel), "observed": round(obs, 3),
                      "model": round(1 / (1 + math.exp(-coef * math.log(mid))), 3)})
    return {"b": coef, "n": len(xs) // 2, "se": se, "calibration": calib}


def replacement_p1(b: dict, coef: float) -> float:
    x = ratio_feature(b.get("s1"), b.get("s2"))
    if x is None:
        return 0.5
    return 1 / (1 + math.exp(-coef * x))
