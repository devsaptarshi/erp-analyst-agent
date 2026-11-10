"""Structural tests on the committed golden question set
(tests/fixtures/golden_questions.json) — these don't need a database
connection (the fixture is already generated), so they run as part of the
normal fast unit suite and catch drift if the fixture is ever
regenerated without matching the spec's required category counts.
"""
import json
from pathlib import Path

import pytest

from erp_analyst.eval.golden_questions import GoldenQuestion, load

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures/golden_questions.json"

EXPECTED_CATEGORY_COUNTS = {
    "simple_lookup": 30,
    "metric_definition": 35,
    "multi_table_join": 30,
    "time_logic": 20,
    "ambiguous": 15,
    "unanswerable": 15,
    "messy_wording": 5,
}


@pytest.fixture(scope="module")
def questions() -> list[GoldenQuestion]:
    if not FIXTURE_PATH.exists():
        pytest.skip("golden_questions.json not generated — run scripts/generate_golden_questions.py first.")
    return load(FIXTURE_PATH)


def test_total_question_count_is_150(questions):
    assert len(questions) == 150


def test_category_counts_match_the_spec_exactly(questions):
    counts: dict[str, int] = {}
    for q in questions:
        counts[q.category] = counts.get(q.category, 0) + 1
    assert counts == EXPECTED_CATEGORY_COUNTS


def test_exactly_40_questions_are_held_out(questions):
    assert sum(1 for q in questions if q.held_out) == 40


def test_every_category_has_at_least_one_held_out_and_one_visible_question(questions):
    by_category: dict[str, list[GoldenQuestion]] = {}
    for q in questions:
        by_category.setdefault(q.category, []).append(q)
    for cat, qs in by_category.items():
        held = [q for q in qs if q.held_out]
        visible = [q for q in qs if not q.held_out]
        assert held, f"{cat} has no held-out questions"
        assert visible, f"{cat} has no visible questions"


def test_every_question_id_is_unique(questions):
    ids = [q.id for q in questions]
    assert len(ids) == len(set(ids))


def test_every_answer_question_has_a_non_null_ground_truth_and_sql(questions):
    for q in questions:
        if q.behavior == "answer":
            assert q.ground_truth_sql, f"{q.id} has behavior=answer but no ground_truth_sql"
            assert q.expected_result is not None, f"{q.id} has behavior=answer but expected_result is None"


def test_clarify_and_unanswerable_questions_have_no_sql_ground_truth(questions):
    for q in questions:
        if q.behavior in ("clarify", "unanswerable"):
            assert q.ground_truth_sql is None, f"{q.id} is {q.behavior} but has ground_truth_sql set"


def test_unanswerable_questions_each_have_a_documented_reason(questions):
    for q in questions:
        if q.behavior == "unanswerable":
            assert len(q.notes) > 10, f"{q.id} has no real reason recorded in notes"


def test_every_question_text_is_nonempty_and_distinct(questions):
    texts = [q.question for q in questions]
    assert all(len(t) > 5 for t in texts)
    # Not asserting full global uniqueness: multi-tenant templates
    # legitimately repeat phrasing with a different tenant name baked in —
    # but the (question, tenant_name) pair must be unique.
    pairs = [(q.question, q.tenant_name) for q in questions]
    assert len(pairs) == len(set(pairs))


def test_the_fixture_file_matches_what_load_parses(questions):
    raw = json.loads(FIXTURE_PATH.read_text())
    assert len(raw) == len(questions)
