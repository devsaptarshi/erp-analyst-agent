"""A plain-text schema description handed to the model as part of its
prompt. Week 1: a flat table/column listing. The semantic layer (business
metric definitions, dimension synonyms, "a quarter means the Indian
financial year") is a Week 2 item — see the build spec — and will extend
this, not replace it.
"""

SCHEMA_CONTEXT = """\
You are writing read-only analytics SQL (PostgreSQL dialect) against a
multi-tenant manufacturing ERP. Every table below is already filtered to
the current tenant by row-level security — you never need to (and must
never try to) filter by tenant_id yourself.

Tables and columns:

tenants(id, name, created_at)
plants(id, tenant_id, name, location, created_at)
suppliers(id, tenant_id, name, contact_email, created_at)
customers(id, tenant_id, name, region, created_at)
products(id, tenant_id, sku, name, unit, created_at)
materials(id, tenant_id, sku, name, unit, created_at)
employees(id, tenant_id, plant_id, name, role, created_at)

purchase_orders(id, tenant_id, supplier_id, plant_id, order_date, status['open','partial','cancelled','closed'], created_at)
purchase_order_lines(id, tenant_id, purchase_order_id, material_id, qty_ordered, unit, unit_price, created_at)
goods_receipts(id, tenant_id, purchase_order_line_id, qty_received, received_date, created_at)

work_orders(id, tenant_id, plant_id, product_id, qty_planned, status['planned','in_progress','completed','cancelled'], start_date, end_date, created_at)
production_batches(id, tenant_id, work_order_id, batch_number, qty_input, good_output, scrap_output, produced_date, created_at)
batch_inputs(id, tenant_id, production_batch_id, material_id, qty_used, unit, created_at)
quality_checks(id, tenant_id, production_batch_id, check_date, result['pass','fail', NULL=missing check], inspector_employee_id, created_at)

warehouses(id, tenant_id, plant_id, name, created_at)
stock_movements(id, tenant_id, warehouse_id, item_type['material','product'], item_id, movement_type['receipt','issue','transfer','adjustment'], qty, unit, movement_date, created_at)

sales_orders(id, tenant_id, customer_id, plant_id, order_date, status['open','cancelled','closed'], created_at)
sales_order_lines(id, tenant_id, sales_order_id, product_id, qty_ordered, unit_price, created_at)
invoices(id, tenant_id, sales_order_id, invoice_date, amount, status['issued','cancelled','paid'], created_at)
payments(id, tenant_id, invoice_id, payment_date, amount, created_at)

Notes:
- A material's/product's canonical unit lives on materials.unit /
  products.unit. Transaction-line "unit" columns (purchase_order_lines,
  batch_inputs, stock_movements) are recorded separately and sometimes
  disagree with the canonical unit (data-entry inconsistency) — be
  careful summing across rows with different units.
- There is no supplier_id column linking production to purchasing
  directly. To find which supplier's material was used in a production
  batch, trace: production_batches -> batch_inputs (material_id) ->
  the most recent goods_receipts.received_date at or before the batch's
  produced_date for that material -> purchase_order_lines ->
  purchase_orders -> suppliers.
- Revenue-style questions should exclude invoices with status='cancelled'.
- Only a single SELECT statement is allowed, from the tables above. No
  writes, no DDL, no multi-statement SQL, no set_config/current_setting/
  pg_sleep/dblink/pg_* functions. Every join needs an explicit ON/USING
  condition.
"""
