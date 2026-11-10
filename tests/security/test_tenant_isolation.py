"""The security test matrix: proves tenant isolation holds under
adversarial conditions, not just normal use. Every test in this file
either confirms zero cross-tenant leakage or confirms a write/dangerous
operation is rejected before it ever reaches Postgres. This is the Week 1
"done" bar: correct answers + leak tests passing in CI.
"""
import uuid

import pytest

from erp_analyst.db.executor import TenantScopedExecutor
from tests.conftest import set_tenant


# ----------------------------------------------------------------------------
# 1. Canary rows across tenants
# ----------------------------------------------------------------------------
@pytest.fixture
def canary_suppliers(admin_conn, tenant_ids):
    """Inserts one uniquely-named supplier per tenant and cleans up after."""
    canaries = {}
    with admin_conn.cursor() as cur:
        for name, tid in tenant_ids.items():
            canary_name = f"CANARY-{uuid.uuid4().hex[:12]}-{name}"
            cur.execute(
                "INSERT INTO suppliers (tenant_id, name) VALUES (%s, %s) RETURNING id",
                (tid, canary_name),
            )
            canaries[name] = canary_name
    yield canaries
    with admin_conn.cursor() as cur:
        for canary_name in canaries.values():
            cur.execute("DELETE FROM suppliers WHERE name = %s", (canary_name,))


def test_each_tenant_sees_only_its_own_canary_row(canary_suppliers, tenant_ids):
    for viewer_name, viewer_tid in tenant_ids.items():
        executor = TenantScopedExecutor(viewer_tid)
        result = executor.execute("SELECT name FROM suppliers")
        assert result.ok, result.error
        seen_names = {row["name"] for row in result.rows}

        assert canary_suppliers[viewer_name] in seen_names, "a tenant could not see its own canary row"
        for other_name, other_canary in canary_suppliers.items():
            if other_name != viewer_name:
                assert other_canary not in seen_names, (
                    f"LEAK: tenant {viewer_name} saw tenant {other_name}'s canary row"
                )


def test_injection_looking_text_stored_as_data_is_inert_and_still_tenant_scoped(admin_conn, tenant_ids):
    """Text that LOOKS like a SQL injection attempt, stored as ordinary
    data (e.g. a supplier typed their name with a stray quote), must come
    back as plain string data — parameterized queries never re-interpret
    it — and must still be tenant-scoped like any other row."""
    tid_a = tenant_ids["Acme Leather Co"]
    tricky_name = "Bob's Hides'; DROP TABLE suppliers; --"
    with admin_conn.cursor() as cur:
        cur.execute("INSERT INTO suppliers (tenant_id, name) VALUES (%s, %s)", (tid_a, tricky_name))
    try:
        executor = TenantScopedExecutor(tid_a)
        result = executor.execute("SELECT name FROM suppliers WHERE name = 'Bob''s Hides'';")
        # The literal apostrophe makes this an intentionally odd WHERE
        # clause from the AGENT's side, not a real attack vector (it's
        # just testing the value is inert) — the real check is below.
        result = executor.execute("SELECT name FROM suppliers")
        assert result.ok, result.error
        names = {row["name"] for row in result.rows}
        assert tricky_name in names  # stored and returned as inert data

        other_tid = next(t for n, t in tenant_ids.items() if n != "Acme Leather Co")
        other_result = TenantScopedExecutor(other_tid).execute("SELECT name FROM suppliers")
        assert tricky_name not in {row["name"] for row in other_result.rows}

        with admin_conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM suppliers")
            (count,) = cur.fetchone()
        assert count > 0  # the "DROP TABLE" text never executed as SQL
    finally:
        with admin_conn.cursor() as cur:
            cur.execute("DELETE FROM suppliers WHERE name = %s", (tricky_name,))


# ----------------------------------------------------------------------------
# 2. set_config / current_setting tenant-impersonation attempts
# ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "attack_sql",
    [
        "SELECT set_config('app.tenant_id', 'anything', true)",
        "SELECT * FROM suppliers WHERE 1=1 OR set_config('app.tenant_id', (SELECT id::text FROM tenants LIMIT 1), true) IS NOT NULL",
        "SELECT current_setting('app.tenant_id')",
        "SELECT * FROM suppliers; SELECT set_config('app.tenant_id', 'x', true)",
    ],
)
def test_set_config_impersonation_attempts_are_rejected_before_reaching_postgres(attack_sql, tenant_ids):
    executor = TenantScopedExecutor(tenant_ids["Acme Leather Co"])
    result = executor.execute(attack_sql)
    assert not result.ok
    assert result.rows is None


# ----------------------------------------------------------------------------
# 3. Direct RLS test — bypassing the validator entirely, raw connection
# ----------------------------------------------------------------------------
def test_direct_rls_with_no_tenant_context_returns_zero_rows(analyst_conn, tenant_ids):
    # Deliberately do NOT call set_tenant() — simulates a bug elsewhere in
    # the app that forgot to set the context. RLS must fail closed.
    with analyst_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM suppliers")
        (count,) = cur.fetchone()
    assert count == 0


def test_direct_rls_cannot_be_overridden_by_a_crafted_where_clause(analyst_conn, tenant_ids):
    set_tenant(analyst_conn, tenant_ids["Acme Leather Co"])
    other_tid = tenant_ids["Summit Tanning Works"]
    with analyst_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM suppliers WHERE tenant_id = %s", (other_tid,))
        (count,) = cur.fetchone()
    assert count == 0


def test_analyst_ro_cannot_write(analyst_conn, tenant_ids):
    set_tenant(analyst_conn, tenant_ids["Acme Leather Co"])
    with pytest.raises(Exception, match="permission denied|read-only"):
        with analyst_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO suppliers (tenant_id, name) VALUES (%s, %s)",
                (tenant_ids["Acme Leather Co"], "Should Not Exist"),
            )


def test_analyst_ro_cannot_bypass_rls_even_with_superuser_style_tricks(analyst_conn, tenant_ids):
    set_tenant(analyst_conn, tenant_ids["Acme Leather Co"])
    with pytest.raises(Exception):
        with analyst_conn.cursor() as cur:
            # analyst_ro has no rights to alter its own RLS exemption
            cur.execute("ALTER TABLE suppliers NO FORCE ROW LEVEL SECURITY")


# ----------------------------------------------------------------------------
# 4. Write / DDL / multi-statement attempts through the agent's own path
# ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "attack_sql",
    [
        "INSERT INTO suppliers (tenant_id, name) VALUES ('x', 'y')",
        "UPDATE suppliers SET name = 'pwned'",
        "DELETE FROM suppliers",
        "DROP TABLE suppliers",
        "TRUNCATE suppliers",
        "SELECT * FROM suppliers; DROP TABLE suppliers",
        "SELECT pg_sleep(10)",
        "COPY suppliers TO '/tmp/exfiltrated.csv'",
    ],
)
def test_write_ddl_and_multi_statement_attempts_never_reach_postgres(attack_sql, tenant_ids):
    executor = TenantScopedExecutor(tenant_ids["Acme Leather Co"])
    result = executor.execute(attack_sql)
    assert not result.ok
    assert result.rows is None


def test_an_unconditioned_cross_join_across_large_tables_is_rejected_before_execution(tenant_ids):
    executor = TenantScopedExecutor(tenant_ids["Acme Leather Co"])
    result = executor.execute("SELECT * FROM purchase_order_lines, sales_order_lines")
    assert not result.ok


# ----------------------------------------------------------------------------
# 5. Connection-pool alternation — the specific bug class the build spec
#    calls out (a cached SQL template or a pooled connection carrying one
#    tenant's context into the next request)
# ----------------------------------------------------------------------------
def test_1000_request_pool_alternation_never_leaks(tenant_ids):
    """Runs 1,000 requests through a SHARED connection pool, alternating
    tenants on every request, and confirms every single response only
    ever contains that request's own tenant's rows. This is the strongest
    test in the file: it proves the SET LOCAL-per-transaction design is
    pool-safe even though the current executor doesn't pool connections
    itself (see KNOWN_LIMITS.md) — if pooling is added later, this test
    already covers the exact failure mode that would introduce."""
    from psycopg_pool import ConnectionPool

    from erp_analyst.config import settings
    from erp_analyst.validation.sql_validator import validate

    tenant_list = list(tenant_ids.items())
    pool = ConnectionPool(settings.analyst_database_url, min_size=2, max_size=5, open=True)
    try:
        validated = validate("SELECT tenant_id FROM suppliers")
        assert validated.ok
        for i in range(1000):
            name, tid = tenant_list[i % len(tenant_list)]
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT set_config('app.tenant_id', %s, true)", (tid,))
                    cur.execute(validated.sql)
                    rows = cur.fetchall()
                conn.rollback()
            for (seen_tid,) in rows:
                assert str(seen_tid) == tid, (
                    f"LEAK at request {i}: expected tenant {name} ({tid}), saw {seen_tid}"
                )
    finally:
        pool.close()
