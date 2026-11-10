-- Row-Level Security: the authoritative isolation layer. This holds even
-- if the SQL validator or the application layer has a bug — it is
-- enforced by Postgres itself, on the `analyst_ro` role, independent of
-- anything the agent or the model does.
--
-- Run by scripts/init_db.py AFTER schema.sql and AFTER the analyst_ro
-- role exists (role creation + password happen in Python, not here — see
-- init_db.py; a password never belongs in a file committed to git).

-- `tenants` itself is included: without a policy here, analyst_ro could
-- list every tenant's name, which is itself a cross-tenant leak (just of
-- metadata rather than business data). Keyed on `id`, since a tenant IS
-- its own identifier.
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON tenants;
CREATE POLICY tenant_isolation ON tenants
    USING (id = current_setting('app.tenant_id', true)::uuid);

-- Every other table carries tenant_id directly.
DO $$
DECLARE
    tbl text;
BEGIN
    FOREACH tbl IN ARRAY ARRAY[
        'plants', 'suppliers', 'customers', 'products', 'materials', 'employees',
        'purchase_orders', 'purchase_order_lines', 'goods_receipts',
        'work_orders', 'production_batches', 'batch_inputs', 'quality_checks',
        'warehouses', 'stock_movements',
        'sales_orders', 'sales_order_lines', 'invoices', 'payments'
    ]
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', tbl);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_setting(''app.tenant_id'', true)::uuid)',
            tbl
        );
    END LOOP;
END $$;

-- Read-only grants. No INSERT/UPDATE/DELETE, ever — the agent is never
-- given a write tool at the application layer either (defense in depth).
GRANT CONNECT ON DATABASE erp_analyst TO analyst_ro;
GRANT USAGE ON SCHEMA public TO analyst_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO analyst_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO analyst_ro;

-- A per-session statement timeout as a backstop against an expensive or
-- runaway query that the SQL validator's EXPLAIN-based cost check didn't
-- catch. The application layer sets this per-connection too (belt and
-- braces); this is the role-level default.
ALTER ROLE analyst_ro SET statement_timeout = '5s';
