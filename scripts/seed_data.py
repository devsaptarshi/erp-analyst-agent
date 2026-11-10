#!/usr/bin/env python3
"""Generates synthetic data for 3 tenants, 18 months of history, with a
fixed seed for determinism and deliberate messiness + "planted facts" for
eval ground truth. Entirely fake — see README's "Important: synthetic
project" section. Run as the admin user; analyst_ro has no write access.

Usage: uv run python scripts/seed_data.py [--wipe]
"""
import argparse
import random
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import psycopg
from faker import Faker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from erp_analyst.config import settings  # noqa: E402

SEED = 20261110
random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

TODAY = date(2026, 11, 1)
HISTORY_START = TODAY - timedelta(days=18 * 30)  # ~18 months

# The "planted fact" each eval question set can rely on as ground truth:
# for tenant 0, the supplier "Northline Hides" has a visible yield crash
# in a specific quarter, traceable through production_batches ->
# batch_inputs -> materials <- purchase_order_lines (nearest earlier
# goods receipt for that material/plant) -> purchase_orders -> suppliers.
PLANTED_BAD_SUPPLIER_NAME = "Northline Hides"
PLANTED_BAD_QUARTER_START = date(2026, 4, 1)
PLANTED_BAD_QUARTER_END = date(2026, 6, 30)


def uid() -> str:
    return str(uuid.uuid4())


@dataclass
class TenantCtx:
    tenant_id: str
    name: str
    plants: list[str] = field(default_factory=list)
    suppliers: list[dict] = field(default_factory=list)  # {id, name}
    customers: list[str] = field(default_factory=list)
    products: list[dict] = field(default_factory=list)  # {id, unit}
    materials: list[dict] = field(default_factory=list)  # {id, unit}
    employees: list[dict] = field(default_factory=list)  # {id, plant_id}
    warehouses: list[dict] = field(default_factory=list)  # {id, plant_id}
    # material_id -> sorted list of (date, supplier_id) from purchase_order_lines'
    # goods receipts, used to pick "who most recently supplied this
    # material" when generating production batches.
    material_supply_history: dict[str, list[tuple[date, str]]] = field(default_factory=dict)
    planted_bad_supplier_id: str | None = None


UNITS_MATERIAL = ["kg", "sqft", "litre"]
UNITS_PRODUCT = ["each", "sqft"]

# A handful of near-duplicate spellings fed in for the SAME supplier
# identity across different purchase orders, simulating inconsistent data
# entry — a real analytics question ("how much did we buy from Shanti
# Tanning") has to cope with this via the semantic layer's synonyms, not
# by the data being clean.
SUPPLIER_NAME_VARIANTS = {
    "Shanti Tanning Co.": ["Shanti Tanning Co.", "Shanti Tanning Co", "SHANTI TANNING CO"],
}


def gen_tenant_master_data(conn: psycopg.Connection, tenant_name: str, plant_cities: list[str]) -> TenantCtx:
    ctx = TenantCtx(tenant_id=uid(), name=tenant_name)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO tenants (id, name) VALUES (%s, %s)", (ctx.tenant_id, ctx.name))

        for city in plant_cities:
            plant_id = uid()
            cur.execute(
                "INSERT INTO plants (id, tenant_id, name, location) VALUES (%s, %s, %s, %s)",
                (plant_id, ctx.tenant_id, f"{tenant_name} Plant - {city}", city),
            )
            ctx.plants.append(plant_id)

            for _ in range(random.randint(1, 2)):
                wh_id = uid()
                cur.execute(
                    "INSERT INTO warehouses (id, tenant_id, plant_id, name) VALUES (%s, %s, %s, %s)",
                    (wh_id, ctx.tenant_id, plant_id, f"WH-{fake.word().capitalize()}"),
                )
                ctx.warehouses.append({"id": wh_id, "plant_id": plant_id})

            for _ in range(random.randint(4, 7)):
                emp_id = uid()
                cur.execute(
                    "INSERT INTO employees (id, tenant_id, plant_id, name, role) VALUES (%s, %s, %s, %s, %s)",
                    (emp_id, ctx.tenant_id, plant_id, fake.name(), random.choice(["Inspector", "Operator", "Supervisor", "Planner"])),
                )
                ctx.employees.append({"id": emp_id, "plant_id": plant_id})

        supplier_base_names = [f"{fake.company()} {random.choice(['Tanning', 'Hides', 'Leather', 'Traders'])}" for _ in range(6)]
        supplier_base_names.append(PLANTED_BAD_SUPPLIER_NAME if tenant_name == "Acme Leather Co" else f"{fake.company()} Supply")
        for name in supplier_base_names:
            variants = SUPPLIER_NAME_VARIANTS.get(name, [name])
            sid = uid()
            cur.execute(
                "INSERT INTO suppliers (id, tenant_id, name, contact_email) VALUES (%s, %s, %s, %s)",
                (sid, ctx.tenant_id, random.choice(variants), fake.company_email()),
            )
            ctx.suppliers.append({"id": sid, "name": name})
            if name == PLANTED_BAD_SUPPLIER_NAME:
                ctx.planted_bad_supplier_id = sid

        for _ in range(random.randint(5, 8)):
            cid = uid()
            cur.execute(
                "INSERT INTO customers (id, tenant_id, name, region) VALUES (%s, %s, %s, %s)",
                (cid, ctx.tenant_id, fake.company(), random.choice(["North", "South", "East", "West", "Export"])),
            )
            ctx.customers.append(cid)

        for _ in range(random.randint(5, 8)):
            pid = uid()
            unit = random.choice(UNITS_PRODUCT)
            cur.execute(
                "INSERT INTO products (id, tenant_id, sku, name, unit) VALUES (%s, %s, %s, %s, %s)",
                (pid, ctx.tenant_id, f"FG-{fake.bothify('???-####').upper()}", f"Finished {fake.word().capitalize()} Leather", unit),
            )
            ctx.products.append({"id": pid, "unit": unit})

        for _ in range(random.randint(5, 8)):
            mid = uid()
            unit = random.choice(UNITS_MATERIAL)
            cur.execute(
                "INSERT INTO materials (id, tenant_id, sku, name, unit) VALUES (%s, %s, %s, %s, %s)",
                (mid, ctx.tenant_id, f"RM-{fake.bothify('???-####').upper()}", f"Raw {fake.word().capitalize()} Hide", unit),
            )
            ctx.materials.append({"id": mid, "unit": unit})
            ctx.material_supply_history[mid] = []

    return ctx


def random_date_in_history() -> date:
    days = (TODAY - HISTORY_START).days
    return HISTORY_START + timedelta(days=random.randint(0, days))


def gen_purchasing(conn: psycopg.Connection, ctx: TenantCtx) -> None:
    with conn.cursor() as cur:
        for plant_id in ctx.plants:
            # Roughly weekly purchase orders over the 18-month history.
            n_weeks = (TODAY - HISTORY_START).days // 7
            for week in range(n_weeks):
                if random.random() > 0.6:
                    continue
                order_date = HISTORY_START + timedelta(weeks=week, days=random.randint(0, 6))
                supplier = random.choice(ctx.suppliers)
                # Messiness: some POs cancelled, some partial, most closed.
                status = random.choices(["closed", "partial", "cancelled", "open"], weights=[70, 15, 10, 5])[0]
                po_id = uid()
                cur.execute(
                    "INSERT INTO purchase_orders (id, tenant_id, supplier_id, plant_id, order_date, status) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (po_id, ctx.tenant_id, supplier["id"], plant_id, order_date, status),
                )
                for _ in range(random.randint(1, 3)):
                    material = random.choice(ctx.materials)
                    qty = round(random.uniform(50, 2000), 2)
                    # Messiness: the line's recorded unit sometimes doesn't
                    # match the material's canonical unit (data-entry
                    # inconsistency — a real analytics question has to
                    # either normalize or flag this, not silently sum
                    # mismatched units).
                    line_unit = material["unit"] if random.random() > 0.08 else random.choice(UNITS_MATERIAL)
                    unit_price = round(random.uniform(2, 80), 2)
                    line_id = uid()
                    cur.execute(
                        "INSERT INTO purchase_order_lines (id, tenant_id, purchase_order_id, material_id, qty_ordered, unit, unit_price) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (line_id, ctx.tenant_id, po_id, material["id"], qty, line_unit, unit_price),
                    )
                    if status in ("closed", "partial"):
                        received_qty = qty if status == "closed" else round(qty * random.uniform(0.3, 0.9), 2)
                        received_date = order_date + timedelta(days=random.randint(3, 21))
                        cur.execute(
                            "INSERT INTO goods_receipts (id, tenant_id, purchase_order_line_id, qty_received, received_date) "
                            "VALUES (%s, %s, %s, %s, %s)",
                            (uid(), ctx.tenant_id, line_id, received_qty, received_date),
                        )
                        ctx.material_supply_history[material["id"]].append((received_date, supplier["id"]))

        for hist in ctx.material_supply_history.values():
            hist.sort(key=lambda t: t[0])


def supplier_for_material_at(ctx: TenantCtx, material_id: str, as_of: date) -> str | None:
    hist = ctx.material_supply_history.get(material_id, [])
    chosen = None
    for d, supplier_id in hist:
        if d <= as_of:
            chosen = supplier_id
        else:
            break
    return chosen


def gen_production_and_sales(conn: psycopg.Connection, ctx: TenantCtx) -> None:
    with conn.cursor() as cur:
        for plant_id in ctx.plants:
            plant_employees = [e["id"] for e in ctx.employees if e["plant_id"] == plant_id]
            plant_warehouses = [w["id"] for w in ctx.warehouses if w["plant_id"] == plant_id]
            n_weeks = (TODAY - HISTORY_START).days // 7

            for week in range(n_weeks):
                if random.random() > 0.5:
                    continue
                start_date = HISTORY_START + timedelta(weeks=week, days=random.randint(0, 6))
                product = random.choice(ctx.products)
                qty_planned = round(random.uniform(100, 1000), 2)
                wo_status = random.choices(["completed", "in_progress", "cancelled"], weights=[80, 10, 10])[0]
                end_date = start_date + timedelta(days=random.randint(2, 10)) if wo_status == "completed" else None
                wo_id = uid()
                cur.execute(
                    "INSERT INTO work_orders (id, tenant_id, plant_id, product_id, qty_planned, status, start_date, end_date) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (wo_id, ctx.tenant_id, plant_id, product["id"], qty_planned, wo_status, start_date, end_date),
                )
                if wo_status != "completed":
                    continue

                for batch_num in range(1, random.randint(1, 3) + 1):
                    produced_date = start_date + timedelta(days=random.randint(0, 9))
                    material = random.choice(ctx.materials)
                    qty_input = round(random.uniform(50, 500), 2)

                    supplier_at_batch = supplier_for_material_at(ctx, material["id"], produced_date)
                    is_planted_bad = (
                        ctx.planted_bad_supplier_id is not None
                        and supplier_at_batch == ctx.planted_bad_supplier_id
                        and PLANTED_BAD_QUARTER_START <= produced_date <= PLANTED_BAD_QUARTER_END
                    )
                    yield_pct = random.uniform(0.55, 0.70) if is_planted_bad else random.uniform(0.88, 0.98)
                    good_output = round(qty_input * yield_pct, 2)
                    scrap_output = round(qty_input - good_output, 2)

                    batch_id = uid()
                    cur.execute(
                        "INSERT INTO production_batches (id, tenant_id, work_order_id, batch_number, qty_input, good_output, scrap_output, produced_date) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (batch_id, ctx.tenant_id, wo_id, f"B-{batch_num:03d}-{produced_date.isoformat()}", qty_input, good_output, scrap_output, produced_date),
                    )
                    cur.execute(
                        "INSERT INTO batch_inputs (id, tenant_id, production_batch_id, material_id, qty_used, unit) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (uid(), ctx.tenant_id, batch_id, material["id"], qty_input, material["unit"]),
                    )

                    # Messiness: ~12% of batches never got a quality check
                    # logged at all (missing data, not a fail).
                    if random.random() > 0.12 and plant_employees:
                        result = random.choices(["pass", "fail"], weights=[90, 10])[0]
                        cur.execute(
                            "INSERT INTO quality_checks (id, tenant_id, production_batch_id, check_date, result, inspector_employee_id) "
                            "VALUES (%s, %s, %s, %s, %s, %s)",
                            (uid(), ctx.tenant_id, batch_id, produced_date + timedelta(days=1), result, random.choice(plant_employees)),
                        )

                    if plant_warehouses:
                        cur.execute(
                            "INSERT INTO stock_movements (id, tenant_id, warehouse_id, item_type, item_id, movement_type, qty, unit, movement_date) "
                            "VALUES (%s, %s, %s, 'product', %s, 'receipt', %s, %s, %s)",
                            (uid(), ctx.tenant_id, random.choice(plant_warehouses), product["id"], good_output, product["unit"], produced_date),
                        )

            # Sales — seasonality: more orders Oct-Dec, fewer in the summer
            # months, so a time-series question has a real pattern to find.
            for week in range(n_weeks):
                order_date = HISTORY_START + timedelta(weeks=week, days=random.randint(0, 6))
                seasonal_boost = 1.6 if order_date.month in (10, 11, 12) else (0.6 if order_date.month in (5, 6, 7) else 1.0)
                if random.random() > 0.5 * seasonal_boost:
                    continue
                customer_id = random.choice(ctx.customers)
                status = random.choices(["closed", "open", "cancelled"], weights=[75, 15, 10])[0]
                so_id = uid()
                cur.execute(
                    "INSERT INTO sales_orders (id, tenant_id, customer_id, plant_id, order_date, status) VALUES (%s, %s, %s, %s, %s, %s)",
                    (so_id, ctx.tenant_id, customer_id, plant_id, order_date, status),
                )
                total = 0.0
                for _ in range(random.randint(1, 3)):
                    product = random.choice(ctx.products)
                    qty = round(random.uniform(10, 300), 2)
                    unit_price = round(random.uniform(15, 150), 2)
                    cur.execute(
                        "INSERT INTO sales_order_lines (id, tenant_id, sales_order_id, product_id, qty_ordered, unit_price) VALUES (%s, %s, %s, %s, %s, %s)",
                        (uid(), ctx.tenant_id, so_id, product["id"], qty, unit_price),
                    )
                    total += qty * unit_price

                if status == "closed":
                    invoice_date = order_date + timedelta(days=random.randint(1, 14))
                    inv_status = random.choices(["paid", "issued"], weights=[80, 20])[0]
                    inv_id = uid()
                    cur.execute(
                        "INSERT INTO invoices (id, tenant_id, sales_order_id, invoice_date, amount, status) VALUES (%s, %s, %s, %s, %s, %s)",
                        (inv_id, ctx.tenant_id, so_id, invoice_date, round(total, 2), inv_status),
                    )
                    if inv_status == "paid":
                        cur.execute(
                            "INSERT INTO payments (id, tenant_id, invoice_id, payment_date, amount) VALUES (%s, %s, %s, %s, %s)",
                            (uid(), ctx.tenant_id, inv_id, invoice_date + timedelta(days=random.randint(1, 30)), round(total, 2)),
                        )
                elif status == "cancelled" and random.random() < 0.3:
                    # Messiness: a cancelled order with an invoice that was
                    # itself then cancelled — tests whether a revenue
                    # question correctly excludes it (see semantic layer's
                    # "revenue excludes cancelled invoices" rule, Week 2).
                    inv_id = uid()
                    cur.execute(
                        "INSERT INTO invoices (id, tenant_id, sales_order_id, invoice_date, amount, status) VALUES (%s, %s, %s, %s, %s, 'cancelled')",
                        (inv_id, ctx.tenant_id, so_id, order_date + timedelta(days=2), round(total, 2)),
                    )


def wipe(conn: psycopg.Connection) -> None:
    tables = [
        "payments", "invoices", "sales_order_lines", "sales_orders",
        "stock_movements", "quality_checks", "batch_inputs", "production_batches", "work_orders",
        "goods_receipts", "purchase_order_lines", "purchase_orders",
        "warehouses", "employees", "materials", "products", "customers", "suppliers", "plants", "tenants",
    ]
    with conn.cursor() as cur:
        for t in tables:
            cur.execute(f"DELETE FROM {t}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wipe", action="store_true", help="Delete all existing rows first.")
    args = parser.parse_args()

    with psycopg.connect(settings.database_url, autocommit=False) as conn:
        if args.wipe:
            wipe(conn)
            conn.commit()

        tenant_defs = [
            ("Acme Leather Co", ["Chennai", "Kanpur"]),
            ("Summit Tanning Works", ["Agra"]),
            ("Riverbend Hides Ltd", ["Jalandhar", "Kolkata"]),
        ]
        for name, cities in tenant_defs:
            print(f"Generating tenant: {name}")
            ctx = gen_tenant_master_data(conn, name, cities)
            gen_purchasing(conn, ctx)
            gen_production_and_sales(conn, ctx)
            conn.commit()
            print(f"  -> tenant_id={ctx.tenant_id}, planted_bad_supplier_id={ctx.planted_bad_supplier_id}")

    print("Done.")


if __name__ == "__main__":
    main()
