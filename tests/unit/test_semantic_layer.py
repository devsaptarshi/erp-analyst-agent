from erp_analyst.semantic.loader import SemanticLayer


def test_loads_the_shipped_layer_yaml_without_error():
    layer = SemanticLayer.load()
    assert layer.version
    assert len(layer.metrics) >= 5
    assert len(layer.dimensions) >= 5
    assert len(layer.business_rules) >= 5


def test_material_yield_pct_is_defined_as_good_over_input_not_good_over_good_plus_scrap():
    layer = SemanticLayer.load()
    metric = layer.metrics["material_yield_pct"]
    assert "good_output" in metric.definition
    assert "qty_input" in metric.definition
    assert "scrap_output" not in metric.definition


def test_revenue_metric_carries_a_cancelled_exclusion_filter():
    layer = SemanticLayer.load()
    metric = layer.metrics["revenue"]
    assert metric.filter is not None
    assert "cancelled" in metric.filter


def test_find_metric_by_term_matches_exact_name():
    layer = SemanticLayer.load()
    assert layer.find_metric_by_term("material_yield_pct") is not None


def test_find_metric_by_term_matches_a_word_in_the_label():
    layer = SemanticLayer.load()
    metric = layer.find_metric_by_term("yield")
    assert metric is not None
    assert metric.name == "material_yield_pct"


def test_find_metric_by_term_returns_none_for_an_unrelated_term():
    layer = SemanticLayer.load()
    assert layer.find_metric_by_term("flibbertigibbet") is None


def test_find_dimension_by_synonym_matches_vendor_to_supplier():
    layer = SemanticLayer.load()
    dim = layer.find_dimension_by_synonym("vendor")
    assert dim is not None
    assert dim.name == "supplier"
    assert dim.table == "suppliers"


def test_find_dimension_by_synonym_matches_the_canonical_name_too():
    layer = SemanticLayer.load()
    dim = layer.find_dimension_by_synonym("supplier")
    assert dim is not None
    assert dim.name == "supplier"


def test_find_dimension_by_synonym_returns_none_for_an_unrelated_term():
    layer = SemanticLayer.load()
    assert layer.find_dimension_by_synonym("spaceship") is None


def test_quarter_definition_business_rule_is_present_and_specifies_indian_financial_year():
    layer = SemanticLayer.load()
    rule_ids = {r.id for r in layer.business_rules}
    assert "quarter_definition" in rule_ids
    rule = next(r for r in layer.business_rules if r.id == "quarter_definition")
    assert "financial" in rule.rule.lower()


def test_no_delivery_due_dates_rule_is_present():
    """This rule exists specifically so the agent answers 'unanswerable'
    rather than inventing a definition of on-time — see the eval's
    unanswerable-question category."""
    layer = SemanticLayer.load()
    rule_ids = {r.id for r in layer.business_rules}
    assert "no_delivery_due_dates" in rule_ids


def test_render_produces_a_nonempty_text_block_mentioning_every_metric_name():
    layer = SemanticLayer.load()
    text = layer.render()
    assert len(text) > 200
    for metric_name in layer.metrics:
        assert metric_name in text
