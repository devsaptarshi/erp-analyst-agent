from erp_analyst.validation.sql_validator import estimate_cost, validate
from tests.conftest import set_tenant


def test_estimate_cost_returns_a_positive_number_for_a_simple_query(analyst_conn, tenant_ids):
    set_tenant(analyst_conn, tenant_ids["Acme Leather Co"])
    result = validate("SELECT * FROM suppliers")
    assert result.ok, result.errors
    cost = estimate_cost(analyst_conn, result.sql)
    assert cost > 0


def test_estimate_cost_is_higher_for_an_unindexed_cross_table_scan_than_a_simple_lookup(analyst_conn, tenant_ids):
    set_tenant(analyst_conn, tenant_ids["Acme Leather Co"])
    cheap = validate("SELECT * FROM suppliers LIMIT 1")
    expensive = validate(
        "SELECT * FROM purchase_orders po JOIN purchase_order_lines pol ON pol.purchase_order_id = po.id "
        "JOIN goods_receipts gr ON gr.purchase_order_line_id = pol.id"
    )
    assert cheap.ok and expensive.ok
    assert estimate_cost(analyst_conn, expensive.sql) > estimate_cost(analyst_conn, cheap.sql)
