"""The full pipeline wired for real: the real LangGraph graph, the real
sqlglot validator, the real TenantScopedExecutor, the real Postgres
instance with RLS — only the LLM call is faked (no API key in this
environment; see KNOWN_LIMITS.md). This is the strongest proof available
right now that generate -> validate -> execute -> answer actually produces
a tenant-correct answer end to end, not just that each piece passes in
isolation.
"""
from erp_analyst.agent.graph import build_graph
from erp_analyst.agent.sql_generation import GeneratedSql


def test_the_planted_yield_fact_is_answerable_end_to_end_through_the_real_graph(tenant_ids):
    """Reproduces the project's own flagship question — "which supplier's
    hides gave the worst yield" — end to end: real graph, real validator,
    real executor, real RLS-scoped Postgres connection."""
    sql = """
    WITH batch_supplier AS (
        SELECT
            pb.good_output, pb.qty_input,
            (
                SELECT po.supplier_id
                FROM goods_receipts gr
                JOIN purchase_order_lines pol ON pol.id = gr.purchase_order_line_id
                JOIN purchase_orders po ON po.id = pol.purchase_order_id
                WHERE pol.material_id = bi.material_id AND gr.received_date <= pb.produced_date
                ORDER BY gr.received_date DESC LIMIT 1
            ) AS supplier_id
        FROM production_batches pb
        JOIN batch_inputs bi ON bi.production_batch_id = pb.id
        WHERE pb.produced_date >= '2026-04-01' AND pb.produced_date <= '2026-06-30'
    )
    SELECT s.name, round(100.0 * sum(bs.good_output) / sum(bs.qty_input), 1) AS yield_pct
    FROM batch_supplier bs JOIN suppliers s ON s.id = bs.supplier_id
    GROUP BY s.name ORDER BY yield_pct ASC LIMIT 5
    """

    def fake_generator(question, prior_errors, prior_sql, tier):
        return GeneratedSql(plan="join production to purchasing via nearest earlier goods receipt", sql=sql)

    graph = build_graph(sql_generator=fake_generator)
    result = graph.invoke(
        {"question": "Which supplier's hides gave the worst yield last quarter?", "tenant_id": tenant_ids["Acme Leather Co"], "model_tier": "cheap"}
    )

    assert result["rows"], f"expected rows, got error state: {result.get('validation_errors')}"
    worst = result["rows"][0]
    assert worst["name"] == "Northline Hides"
    assert float(worst["yield_pct"]) < 80  # the planted crash — everything else sits around 90-96%


def test_the_same_question_for_a_different_tenant_never_sees_the_first_tenants_data(tenant_ids):
    def fake_generator(question, prior_errors, prior_sql, tier):
        return GeneratedSql(plan="list suppliers", sql="SELECT name FROM suppliers")

    graph = build_graph(sql_generator=fake_generator)
    result = graph.invoke(
        {"question": "list my suppliers", "tenant_id": tenant_ids["Summit Tanning Works"], "model_tier": "cheap"}
    )
    names = {row["name"] for row in result["rows"]}
    assert "Northline Hides" not in names  # that's Acme's supplier, not Summit's
