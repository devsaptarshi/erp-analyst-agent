"""Scores one agent run against a GoldenQuestion's expected behavior/
result. Kept as pure functions (no DB, no LLM) so scoring logic itself is
fully unit-testable independent of actually running the agent.
"""
from __future__ import annotations

from erp_analyst.eval.golden_questions import GoldenQuestion


def _coerce_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _scalar_matches(expected: object, actual: object, tol: float = 0.5) -> bool:
    exp_num = _coerce_number(expected)
    act_num = _coerce_number(actual)
    if exp_num is not None and act_num is not None:
        return abs(exp_num - act_num) <= tol
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip().lower() == actual.strip().lower()
    return expected == actual


def _row_matches(expected_row: dict, actual_row: dict) -> bool:
    """A loose match: every value in the SMALLER row must appear,
    approximately, somewhere with a matching key (case-insensitive) in the
    other — accounts for the agent's column aliasing differing from the
    oracle query's (e.g. "yield_pct" vs "material_yield_pct")."""
    actual_lower = {str(k).lower(): v for k, v in actual_row.items()}
    expected_lower = {str(k).lower(): v for k, v in expected_row.items()}
    smaller, larger = (expected_lower, actual_lower) if len(expected_lower) <= len(actual_lower) else (actual_lower, expected_lower)
    matched = 0
    for key, value in smaller.items():
        if key in larger and _scalar_matches(value, larger[key]):
            matched += 1
        else:
            # try matching by VALUE alone against any column in the larger row
            if any(_scalar_matches(value, v) for v in larger.values()):
                matched += 1
    return matched >= max(1, len(smaller) - 1)  # allow exactly one column to differ (e.g. a label vs an id)


def result_matches_expected(expected_result: object, rows: list[dict] | None) -> bool:
    if rows is None:
        return False
    if expected_result is None:
        return len(rows) == 0

    if isinstance(expected_result, list):
        if len(rows) == 0:
            return False
        # Compare the first expected row against the first actual row —
        # good enough for "top N" / "worst X" style questions where order
        # matters; a full set-based comparison would be needed for
        # unordered multi-row results, which none of the golden questions
        # currently are (all use ORDER BY ... LIMIT or GROUP BY with a
        # small, fully-expected row count).
        first_expected = expected_result[0]
        if isinstance(first_expected, dict):
            return any(_row_matches(first_expected, row) for row in rows)
        # a plain list like ["Northline Hides", "90.1"] from a single-row, multi-column oracle query
        if isinstance(first_expected, (str, int, float)) and len(rows) >= 1:
            row_values = list(rows[0].values())
            return any(_scalar_matches(v, rv) for v in expected_result for rv in row_values)
        return False

    # Scalar expected result: compare against the first value of the first row.
    if len(rows) == 0:
        return False
    first_row_values = list(rows[0].values())
    if not first_row_values:
        return False
    return _scalar_matches(expected_result, first_row_values[0])


def score(question: GoldenQuestion, graph_result: dict) -> bool:
    if question.behavior == "clarify":
        return "__interrupt__" in graph_result

    if question.behavior == "unanswerable":
        # Correct if the agent did NOT confidently return rows — it either
        # failed validation/execution (rows is None) or, if it somehow
        # produced rows, that's scored as a miss (a model should recognize
        # it has no way to answer, not guess with whatever columns exist).
        return graph_result.get("rows") is None

    # behavior == "answer"
    if "__interrupt__" in graph_result:
        return False  # should have just answered; asking for clarification here is itself a miss
    return result_matches_expected(question.expected_result, graph_result.get("rows"))
