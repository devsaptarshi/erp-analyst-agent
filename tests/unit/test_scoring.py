from erp_analyst.eval.golden_questions import GoldenQuestion
from erp_analyst.eval.scoring import result_matches_expected, score


def make_question(behavior, expected_result=None) -> GoldenQuestion:
    return GoldenQuestion(
        id="q1",
        category="simple_lookup",
        tenant_name="Acme",
        question="x",
        behavior=behavior,
        ground_truth_sql="SELECT 1" if behavior == "answer" else None,
        expected_result=expected_result,
        notes="",
    )


class TestScalarResults:
    def test_a_matching_scalar_count_is_correct(self):
        q = make_question("answer", expected_result=7)
        assert score(q, {"rows": [{"count": 7}]}) is True

    def test_a_matching_scalar_with_small_float_tolerance_is_correct(self):
        q = make_question("answer", expected_result=92.5)
        assert score(q, {"rows": [{"yield_pct": 92.7}]}) is True  # within 0.5 tolerance

    def test_a_scalar_outside_tolerance_is_wrong(self):
        q = make_question("answer", expected_result=92.5)
        assert score(q, {"rows": [{"yield_pct": 50.0}]}) is False

    def test_a_scalar_as_string_vs_number_still_matches(self):
        q = make_question("answer", expected_result=7)
        assert score(q, {"rows": [{"count": "7"}]}) is True

    def test_no_rows_at_all_is_wrong_for_an_answer_question(self):
        q = make_question("answer", expected_result=7)
        assert score(q, {"rows": None}) is False

    def test_empty_rows_for_a_nonzero_expected_scalar_is_wrong(self):
        q = make_question("answer", expected_result=7)
        assert score(q, {"rows": []}) is False

    def test_expected_none_with_empty_rows_is_correct(self):
        # e.g. an aggregate over zero matching rows legitimately returns nothing.
        make_question("answer", expected_result=None)
        assert result_matches_expected(None, []) is True


class TestListResults:
    def test_a_list_of_dicts_expected_matches_when_the_key_fact_is_present(self):
        q = make_question("answer", expected_result=[{"name": "Northline Hides", "yield_pct": "65.7"}])
        actual_rows = [{"name": "Northline Hides", "yield_pct": 65.7}]
        assert score(q, {"rows": actual_rows}) is True

    def test_a_list_of_dicts_expected_matches_despite_different_column_aliasing(self):
        q = make_question("answer", expected_result=[{"name": "Acme Co", "yield_pct": "90.0"}])
        actual_rows = [{"supplier_name": "Acme Co", "material_yield_pct": 90.1}]
        assert score(q, {"rows": actual_rows}) is True

    def test_a_list_of_dicts_expected_is_wrong_when_the_top_result_differs(self):
        q = make_question("answer", expected_result=[{"name": "Northline Hides", "yield_pct": "65.7"}])
        actual_rows = [{"name": "Some Other Supplier", "yield_pct": 95.0}]
        assert score(q, {"rows": actual_rows}) is False

    def test_a_plain_value_list_expected_matches_a_single_row_with_those_values(self):
        q = make_question("answer", expected_result=["Northline Hides", "65.7"])
        actual_rows = [{"name": "Northline Hides", "yield_pct": 65.7}]
        assert score(q, {"rows": actual_rows}) is True


class TestClarifyQuestions:
    def test_a_clarify_question_is_correct_when_the_graph_actually_interrupted(self):
        q = make_question("clarify")
        assert score(q, {"__interrupt__": [object()]}) is True

    def test_a_clarify_question_is_wrong_if_the_agent_just_answered_instead(self):
        q = make_question("clarify")
        assert score(q, {"rows": [{"x": 1}], "answer": "Found 1 row."}) is False


class TestUnanswerableQuestions:
    def test_an_unanswerable_question_is_correct_when_the_agent_produced_no_rows(self):
        q = make_question("unanswerable")
        assert score(q, {"rows": None, "answer": "I can't answer this with the available data."}) is True

    def test_an_unanswerable_question_is_wrong_if_the_agent_confidently_returned_rows(self):
        q = make_question("unanswerable")
        assert score(q, {"rows": [{"made_up_value": 42}]}) is False


class TestCrossCategoryMisfires:
    def test_an_answer_question_that_the_agent_paused_to_clarify_on_is_wrong(self):
        q = make_question("answer", expected_result=7)
        assert score(q, {"__interrupt__": [object()], "rows": None}) is False
