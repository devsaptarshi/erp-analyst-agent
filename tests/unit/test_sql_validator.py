import pytest

from erp_analyst.validation.sql_validator import DEFAULT_MAX_LIMIT, validate


def test_a_simple_allowed_select_passes():
    result = validate("SELECT name FROM suppliers WHERE tenant_id = 'x'")
    assert result.ok, result.errors


def test_a_select_joining_allowed_tables_with_an_on_clause_passes():
    result = validate(
        "SELECT s.name, sum(po.id::text) FROM suppliers s "
        "JOIN purchase_orders po ON po.supplier_id = s.id GROUP BY s.name"
    )
    assert result.ok, result.errors


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO suppliers (name) VALUES ('x')",
        "UPDATE suppliers SET name = 'x'",
        "DELETE FROM suppliers",
        "DROP TABLE suppliers",
        "ALTER TABLE suppliers ADD COLUMN x text",
        "TRUNCATE suppliers",
        "SET app.tenant_id = 'x'",
        "GRANT SELECT ON suppliers TO public",
        "COPY suppliers TO '/tmp/x.csv'",
    ],
)
def test_non_select_statements_are_rejected(sql):
    result = validate(sql)
    assert not result.ok
    assert result.errors


def test_multiple_statements_are_rejected():
    result = validate("SELECT 1; SELECT 2")
    assert not result.ok
    assert "one statement" in result.errors[0].lower()


def test_a_single_trailing_semicolon_is_fine():
    result = validate("SELECT 1;")
    assert result.ok, result.errors


def test_a_table_not_on_the_allowlist_is_rejected():
    result = validate("SELECT * FROM pg_shadow")
    assert not result.ok
    assert any("pg_shadow" in e for e in result.errors)


@pytest.mark.parametrize("fn", ["set_config", "current_setting", "pg_sleep", "dblink", "pg_read_file"])
def test_explicitly_dangerous_functions_are_rejected_with_a_specific_reason(fn):
    result = validate(f"SELECT {fn}('x', 'y', true) FROM suppliers")
    assert not result.ok
    assert any("blocked" in e for e in result.errors)


def test_a_function_not_on_the_allowlist_is_rejected():
    result = validate("SELECT md5(name) FROM suppliers")
    assert not result.ok
    assert any("not on the allowlist" in e for e in result.errors)


def test_a_comma_separated_from_list_is_rejected_as_an_unconditioned_join():
    result = validate("SELECT * FROM suppliers, customers")
    assert not result.ok
    assert any("cartesian" in e.lower() for e in result.errors)


def test_an_explicit_cross_join_is_rejected():
    result = validate("SELECT * FROM suppliers CROSS JOIN customers")
    assert not result.ok


def test_a_join_with_a_using_clause_is_accepted():
    result = validate("SELECT * FROM suppliers JOIN customers USING (tenant_id)")
    assert result.ok, result.errors


def test_a_query_with_no_limit_gets_one_added():
    result = validate("SELECT * FROM suppliers")
    assert result.ok
    assert f"LIMIT {DEFAULT_MAX_LIMIT}" in result.sql


def test_a_query_with_a_limit_under_the_max_keeps_its_own_limit():
    result = validate("SELECT * FROM suppliers LIMIT 10")
    assert result.ok
    assert "LIMIT 10" in result.sql


def test_a_query_with_a_limit_over_the_max_is_capped():
    result = validate("SELECT * FROM suppliers LIMIT 999999999")
    assert result.ok
    assert f"LIMIT {DEFAULT_MAX_LIMIT}" in result.sql
    assert "999999999" not in result.sql


def test_malformed_sql_is_rejected_cleanly_not_with_a_crash():
    result = validate("SELECT FROM WHERE :::garbage:::")
    assert not result.ok
    assert result.errors


def test_an_empty_string_is_rejected_cleanly():
    result = validate("")
    assert not result.ok


def test_a_subquery_against_an_allowed_table_is_fine():
    result = validate(
        "SELECT name FROM suppliers WHERE id IN (SELECT supplier_id FROM purchase_orders WHERE status = 'closed')"
    )
    assert result.ok, result.errors


def test_a_subquery_touching_a_disallowed_table_is_rejected():
    result = validate("SELECT name FROM suppliers WHERE id IN (SELECT usename FROM pg_user)")
    assert not result.ok


def test_a_where_clause_with_multiple_and_or_conditions_is_not_mistaken_for_an_unknown_function():
    # Regression test: sqlglot's exp.And / exp.Or are subclasses of
    # exp.Func in this version, so a naive "every exp.Func must be on the
    # allowlist" walk flags ordinary boolean logic as an unrecognized
    # function call — found via an end-to-end test with a real multi-
    # condition WHERE clause, not by any of the simpler tests above.
    result = validate(
        "SELECT name FROM suppliers WHERE (tenant_id = 'x' AND name = 'y') OR (tenant_id = 'x' AND name = 'z')"
    )
    assert result.ok, result.errors


def test_date_trunc_is_allowed_despite_sqlglot_renaming_it_internally():
    # Regression test: date_trunc(...) parses to exp.TimestampTrunc, whose
    # .sql_name() is "TIMESTAMP_TRUNC", not "date_trunc" — found via a
    # real seeded verified-query example failing validation.
    result = validate("SELECT date_trunc('month', order_date) FROM purchase_orders")
    assert result.ok, result.errors


def test_a_case_expression_is_not_mistaken_for_an_unknown_function():
    # Regression test: exp.Case/exp.If are also exp.Func subclasses —
    # found the same way as the AND/OR case above.
    result = validate(
        "SELECT CASE WHEN extract(month FROM order_date) IN (4,5,6) THEN 'Q1' ELSE 'other' END FROM purchase_orders"
    )
    assert result.ok, result.errors


def test_a_cte_against_allowed_tables_is_fine():
    result = validate(
        "WITH recent AS (SELECT * FROM purchase_orders WHERE order_date > current_date - 30) "
        "SELECT count(*) FROM recent"
    )
    assert result.ok, result.errors
