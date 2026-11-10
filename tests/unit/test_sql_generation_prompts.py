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


def test_verified_examples_are_rendered_into_the_system_prompt_when_present():
    config = GeneratorConfig(verified_examples=[("how many suppliers", "SELECT count(*) FROM suppliers")])
    prompt = build_system_prompt(config)
    assert "how many suppliers" in prompt
    assert "SELECT count(*) FROM suppliers" in prompt


def test_no_verified_examples_means_no_examples_section():
    prompt = build_system_prompt(GeneratorConfig(verified_examples=None))
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
