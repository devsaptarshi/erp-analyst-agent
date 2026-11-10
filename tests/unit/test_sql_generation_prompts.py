"""Tests the PROMPT CONSTRUCTION (build_system_prompt / build_user_message)
without ever calling a real model — these are pure functions, deliberately
separated from the API-calling code in sql_generation.py so they're
testable without an ANTHROPIC_API_KEY. This is also what the A-E ablation
comparison depends on: these toggles are what distinguish each config.
"""
from erp_analyst.agent.sql_generation import GeneratorConfig, build_system_prompt, build_user_message
from erp_analyst.semantic.loader import SemanticLayer


def test_schema_only_config_does_not_include_the_semantic_layer():
    prompt = build_system_prompt(GeneratorConfig(use_semantic_layer=False))
    assert "material_yield_pct" not in prompt
    assert "suppliers" in prompt  # the raw schema listing is always present


def test_with_semantic_layer_config_includes_metric_definitions():
    prompt = build_system_prompt(GeneratorConfig(use_semantic_layer=True))
    assert "material_yield_pct" in prompt
    assert "quarter_definition" in prompt or "financial year" in prompt


def test_a_custom_semantic_layer_instance_is_used_over_loading_the_default():
    layer = SemanticLayer(version="test", metrics={}, dimensions={}, business_rules=[])
    prompt = build_system_prompt(GeneratorConfig(use_semantic_layer=True), semantic_layer=layer)
    assert "material_yield_pct" not in prompt  # the test layer has no metrics at all


def test_verified_examples_are_rendered_into_the_system_prompt_when_enabled_and_present():
    config = GeneratorConfig(use_verified_queries=True)
    examples = [("how many suppliers", "SELECT count(*) FROM suppliers")]
    prompt = build_system_prompt(config, verified_examples=examples)
    assert "how many suppliers" in prompt
    assert "SELECT count(*) FROM suppliers" in prompt


def test_verified_examples_are_not_rendered_when_the_toggle_is_off_even_if_examples_are_passed():
    config = GeneratorConfig(use_verified_queries=False)
    examples = [("how many suppliers", "SELECT count(*) FROM suppliers")]
    prompt = build_system_prompt(config, verified_examples=examples)
    assert "previously-verified" not in prompt
    assert "how many suppliers" not in prompt


def test_no_verified_examples_means_no_examples_section():
    prompt = build_system_prompt(GeneratorConfig(use_verified_queries=True), verified_examples=None)
    assert "previously-verified" not in prompt


def test_user_message_with_no_prior_errors_is_a_fresh_request():
    msg = build_user_message("How many suppliers do we have?", None, None)
    assert "How many suppliers" in msg
    assert "rejected" not in msg


def test_user_message_with_prior_errors_includes_them_and_the_failed_sql():
    msg = build_user_message("x", ["Table \"pg_shadow\" is not on the allowlist."], "SELECT * FROM pg_shadow")
    assert "pg_shadow" in msg
    assert "rejected" in msg
    assert "SELECT * FROM pg_shadow" in msg


def test_build_user_message_includes_the_clarify_instruction_on_a_fresh_attempt():
    msg = build_user_message("show me revenue", None, None, allow_clarify=True)
    assert "CLARIFY:" in msg


def test_build_user_message_omits_the_clarify_instruction_during_repair():
    msg = build_user_message("show me revenue", ["some error"], "SELECT 1", allow_clarify=True)
    # allow_clarify=True is passed, but prior_errors being set means this
    # is the repair-prompt branch, which never offers CLARIFY at all.
    assert "CLARIFY:" not in msg


def test_build_user_message_omits_the_clarify_instruction_when_explicitly_disabled():
    msg = build_user_message("show me revenue", None, None, allow_clarify=False)
    assert "CLARIFY:" not in msg


def test_parse_response_recognizes_a_clarify_reply():
    from erp_analyst.agent.sql_generation import _parse_response

    result = _parse_response("CLARIFY: Do you mean calendar quarter or fiscal quarter?")
    assert result.clarifying_question == "Do you mean calendar quarter or fiscal quarter?"
    assert result.sql == ""


def test_parse_response_recognizes_a_normal_plan_and_sql_reply():
    from erp_analyst.agent.sql_generation import _parse_response

    result = _parse_response("list suppliers\n```sql\nSELECT name FROM suppliers\n```")
    assert result.clarifying_question is None
    assert result.sql == "SELECT name FROM suppliers"
    assert "list suppliers" in result.plan


def test_make_sql_generator_calls_the_retriever_with_the_actual_question_each_time():
    """Proves retrieval happens PER CALL (so repair attempts and different
    questions get their own relevant examples), not once at generator-
    construction time."""
    from unittest.mock import patch

    from erp_analyst.agent.sql_generation import make_sql_generator

    calls = []

    def fake_retriever(question):
        calls.append(question)
        return [("fake example", "SELECT 1")]

    config = GeneratorConfig(use_verified_queries=True)
    generator = make_sql_generator(config=config, retriever=fake_retriever)

    class FakeResponse:
        content = "plan\n```sql\nSELECT 1\n```"

    with patch("erp_analyst.agent.sql_generation.get_model") as mock_get_model:
        mock_get_model.return_value.invoke.return_value = FakeResponse()
        generator("first question", None, None, "cheap")
        generator("second question", None, None, "cheap")

    assert calls == ["first question", "second question"]
