from erp_analyst.agent.result_check import _parse_check_response, build_check_prompt


def test_build_check_prompt_includes_the_question_sql_and_row_preview():
    prompt = build_check_prompt("How many suppliers?", "SELECT count(*) FROM suppliers", [{"count": 7}])
    assert "How many suppliers?" in prompt
    assert "SELECT count(*) FROM suppliers" in prompt
    assert "count" in prompt


def test_build_check_prompt_only_previews_the_first_5_rows():
    rows = [{"i": i} for i in range(20)]
    prompt = build_check_prompt("x", "SELECT i FROM t", rows)
    assert "{'i': 4}" in prompt
    assert "{'i': 10}" not in prompt


def test_parse_check_response_recognizes_ok():
    result = _parse_check_response("OK")
    assert result.ok is True
    assert result.concern is None


def test_parse_check_response_recognizes_a_concern():
    result = _parse_check_response("CONCERN: The result is empty but the question implies data should exist.")
    assert result.ok is False
    assert "empty" in result.concern


def test_parse_check_response_is_lenient_about_surrounding_whitespace():
    result = _parse_check_response("  OK  \n")
    assert result.ok is True
