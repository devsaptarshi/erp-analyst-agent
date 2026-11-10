-- Synthetic manufacturing ERP schema, designed from scratch for this
-- project. Every table except `tenants` carries `tenant_id`, which is
-- what every RLS policy in rls.sql keys on. Idempotent: safe to re-run.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto; -- gen_random_uuid()

-- ============================= Master data =============================

CREATE TABLE IF NOT EXISTS tenants (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS plants (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id),
    name        text NOT NULL,
    location    text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS suppliers (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id),
    name            text NOT NULL,
    contact_email   text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS customers (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id),
    name        text NOT NULL,
    region      text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS products (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id),
    sku         text NOT NULL,
    name        text NOT NULL,
    unit        text NOT NULL, -- canonical unit, e.g. 'each', 'sqft'
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS materials (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id),
    sku         text NOT NULL,
    name        text NOT NULL,
    unit        text NOT NULL, -- canonical unit, e.g. 'kg', 'sqft', 'litre'
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS employees (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id),
    plant_id    uuid NOT NULL REFERENCES plants(id),
    name        text NOT NULL,
    role        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ============================== Purchasing ==============================

CREATE TABLE IF NOT EXISTS purchase_orders (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id),
    supplier_id     uuid NOT NULL REFERENCES suppliers(id),
    plant_id        uuid NOT NULL REFERENCES plants(id),
    order_date      date NOT NULL,
    status          text NOT NULL CHECK (status IN ('open', 'partial', 'cancelled', 'closed')),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS purchase_order_lines (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           uuid NOT NULL REFERENCES tenants(id),
    purchase_order_id   uuid NOT NULL REFERENCES purchase_orders(id),
    material_id         uuid NOT NULL REFERENCES materials(id),
    qty_ordered         numeric(14, 3) NOT NULL,
    unit                text NOT NULL, -- deliberately may NOT match materials.unit — see data-gen messiness
    unit_price          numeric(14, 4) NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS goods_receipts (
    id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                   uuid NOT NULL REFERENCES tenants(id),
    purchase_order_line_id      uuid NOT NULL REFERENCES purchase_order_lines(id),
    qty_received                numeric(14, 3) NOT NULL,
    received_date               date NOT NULL,
    created_at                  timestamptz NOT NULL DEFAULT now()
);

-- ============================== Production ==============================

CREATE TABLE IF NOT EXISTS work_orders (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id),
    plant_id        uuid NOT NULL REFERENCES plants(id),
    product_id      uuid NOT NULL REFERENCES products(id),
    qty_planned     numeric(14, 3) NOT NULL,
    status          text NOT NULL CHECK (status IN ('planned', 'in_progress', 'completed', 'cancelled')),
    start_date      date NOT NULL,
    end_date        date,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS production_batches (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id),
    work_order_id   uuid NOT NULL REFERENCES work_orders(id),
    batch_number    text NOT NULL,
    qty_input       numeric(14, 3) NOT NULL,
    good_output     numeric(14, 3) NOT NULL,
    scrap_output    numeric(14, 3) NOT NULL DEFAULT 0,
    produced_date   date NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS batch_inputs (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               uuid NOT NULL REFERENCES tenants(id),
    production_batch_id     uuid NOT NULL REFERENCES production_batches(id),
    material_id             uuid NOT NULL REFERENCES materials(id),
    qty_used                numeric(14, 3) NOT NULL,
    unit                    text NOT NULL,
    created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quality_checks (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               uuid NOT NULL REFERENCES tenants(id),
    production_batch_id     uuid NOT NULL REFERENCES production_batches(id),
    check_date              date NOT NULL,
    result                  text CHECK (result IN ('pass', 'fail')), -- NULL = missing check, deliberate messiness
    inspector_employee_id   uuid REFERENCES employees(id),
    created_at              timestamptz NOT NULL DEFAULT now()
);

-- =============================== Inventory ===============================

CREATE TABLE IF NOT EXISTS warehouses (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id),
    plant_id    uuid NOT NULL REFERENCES plants(id),
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stock_movements (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id),
    warehouse_id    uuid NOT NULL REFERENCES warehouses(id),
    item_type       text NOT NULL CHECK (item_type IN ('material', 'product')),
    item_id         uuid NOT NULL, -- polymorphic: materials.id or products.id depending on item_type
    movement_type   text NOT NULL CHECK (movement_type IN ('receipt', 'issue', 'transfer', 'adjustment')),
    qty             numeric(14, 3) NOT NULL,
    unit            text NOT NULL,
    movement_date   date NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- ================================= Sales =================================

CREATE TABLE IF NOT EXISTS sales_orders (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id),
    customer_id     uuid NOT NULL REFERENCES customers(id),
    plant_id        uuid NOT NULL REFERENCES plants(id),
    order_date      date NOT NULL,
    status          text NOT NULL CHECK (status IN ('open', 'cancelled', 'closed')),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sales_order_lines (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id),
    sales_order_id  uuid NOT NULL REFERENCES sales_orders(id),
    product_id      uuid NOT NULL REFERENCES products(id),
    qty_ordered     numeric(14, 3) NOT NULL,
    unit_price      numeric(14, 4) NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS invoices (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id),
    sales_order_id  uuid NOT NULL REFERENCES sales_orders(id),
    invoice_date    date NOT NULL,
    amount          numeric(14, 2) NOT NULL,
    status          text NOT NULL CHECK (status IN ('issued', 'cancelled', 'paid')),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payments (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id),
    invoice_id      uuid NOT NULL REFERENCES invoices(id),
    payment_date    date NOT NULL,
    amount          numeric(14, 2) NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- =========================== Indexes (tenant_id first) ===========================
-- Every multi-tenant table gets tenant_id leading its main index — RLS
-- planning benefits from it, and it documents the isolation boundary.

CREATE INDEX IF NOT EXISTS idx_plants_tenant ON plants(tenant_id);
CREATE INDEX IF NOT EXISTS idx_suppliers_tenant ON suppliers(tenant_id);
CREATE INDEX IF NOT EXISTS idx_customers_tenant ON customers(tenant_id);
CREATE INDEX IF NOT EXISTS idx_products_tenant ON products(tenant_id);
CREATE INDEX IF NOT EXISTS idx_materials_tenant ON materials(tenant_id);
CREATE INDEX IF NOT EXISTS idx_employees_tenant ON employees(tenant_id, plant_id);
CREATE INDEX IF NOT EXISTS idx_po_tenant ON purchase_orders(tenant_id, supplier_id);
CREATE INDEX IF NOT EXISTS idx_pol_tenant ON purchase_order_lines(tenant_id, purchase_order_id);
CREATE INDEX IF NOT EXISTS idx_gr_tenant ON goods_receipts(tenant_id, purchase_order_line_id);
CREATE INDEX IF NOT EXISTS idx_wo_tenant ON work_orders(tenant_id, plant_id, product_id);
CREATE INDEX IF NOT EXISTS idx_pb_tenant ON production_batches(tenant_id, work_order_id);
CREATE INDEX IF NOT EXISTS idx_bi_tenant ON batch_inputs(tenant_id, production_batch_id);
CREATE INDEX IF NOT EXISTS idx_qc_tenant ON quality_checks(tenant_id, production_batch_id);
CREATE INDEX IF NOT EXISTS idx_wh_tenant ON warehouses(tenant_id, plant_id);
CREATE INDEX IF NOT EXISTS idx_sm_tenant ON stock_movements(tenant_id, warehouse_id, item_type, item_id);
CREATE INDEX IF NOT EXISTS idx_so_tenant ON sales_orders(tenant_id, customer_id);
CREATE INDEX IF NOT EXISTS idx_sol_tenant ON sales_order_lines(tenant_id, sales_order_id);
CREATE INDEX IF NOT EXISTS idx_inv_tenant ON invoices(tenant_id, sales_order_id);
CREATE INDEX IF NOT EXISTS idx_pay_tenant ON payments(tenant_id, invoice_id);
