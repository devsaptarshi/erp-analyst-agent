"""McNemar's test for comparing two paired classifiers (here: two ablation
configs' correctness on the SAME golden-question set) — the A-E
comparison's statistical backbone. No scipy dependency: the exact
(binomial) variant uses only stdlib `math.comb`, and the chi-square
variant uses the identity that a chi-square(1) statistic's p-value equals
erfc(sqrt(statistic/2)) (since sqrt(X) for X~chi2(1) is a half-normal),
which `math.erfc` gives directly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class McNemarResult:
    n_a_only: int  # b: config A correct, config B incorrect
    n_b_only: int  # c: config A incorrect, config B correct
    statistic: float
    p_value: float
    method: str  # "exact_binomial" | "chi_square_continuity_corrected"
    significant_at_05: bool


def mcnemar_test(a_correct: list[bool], b_correct: list[bool]) -> McNemarResult:
    """`a_correct`/`b_correct` are the SAME questions' pass/fail under
    config A and config B respectively, same length, same order."""
    if len(a_correct) != len(b_correct):
        raise ValueError("a_correct and b_correct must be the same length (same paired questions).")
    if len(a_correct) == 0:
        raise ValueError("Cannot run McNemar's test on an empty question set.")

    n_a_only = sum(1 for a, b in zip(a_correct, b_correct, strict=True) if a and not b)
    n_b_only = sum(1 for a, b in zip(a_correct, b_correct, strict=True) if b and not a)
    n_discordant = n_a_only + n_b_only

    if n_discordant == 0:
        # No disagreements at all — configs are indistinguishable on this set.
        return McNemarResult(n_a_only, n_b_only, statistic=0.0, p_value=1.0, method="exact_binomial", significant_at_05=False)

    if n_discordant < 25:
        k = min(n_a_only, n_b_only)
        p_value = min(1.0, 2.0 * sum(math.comb(n_discordant, i) for i in range(k + 1)) * (0.5**n_discordant))
        return McNemarResult(n_a_only, n_b_only, statistic=float(k), p_value=p_value, method="exact_binomial", significant_at_05=p_value < 0.05)

    statistic = (abs(n_a_only - n_b_only) - 1) ** 2 / n_discordant
    p_value = math.erfc(math.sqrt(statistic / 2))
    return McNemarResult(
        n_a_only, n_b_only, statistic=statistic, p_value=p_value, method="chi_square_continuity_corrected", significant_at_05=p_value < 0.05
    )
