"""Generates the 150-question golden eval set (spec categories: 30 simple
lookup, 35 metric definition, 30 multi-table joins, 20 time logic, 15
ambiguous, 15 unanswerable, 5 messy wording; 40 held out) against the REAL
seeded data (scripts/seed_data.py) — every "answer"-category question's
ground truth is computed by actually EXECUTING SQL against the admin
connection, never hand-typed, so correctness is guaranteed by the
database, not by careful arithmetic in this file.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import psycopg

Behavior = Literal["answer", "clarify", "unanswerable"]


@dataclass
class GoldenQuestion:
    id: str
    category: str
    tenant_name: str | None
    question: str
    behavior: Behavior
    ground_truth_sql: str | None  # oracle SQL — written freely, not validator-constrained, used only to compute expected_result
    expected_result: object | None  # computed by actually running ground_truth_sql
    notes: str
    held_out: bool = False


def _fetch_tenants(conn: psycopg.Connection) -> list[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute("SELECT name, id FROM tenants ORDER BY name")
        return [(name, str(tid)) for name, tid in cur.fetchall()]


def _fetch_one(conn: psycopg.Connection, sql: str, params: tuple = ()) -> object:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    if row is None:
        return None
    return row[0] if len(row) == 1 else list(row)


def _fetch_all(conn: psycopg.Connection, sql: str, params: tuple = ()) -> list:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def _fetch_scalar(conn: psycopg.Connection, sql_template: str, tenant_id: str) -> object:
    """sql_template must contain exactly one %s for tenant_id."""
    return _fetch_one(conn, sql_template, (tenant_id,))


# ---------------------------------------------------------------------------
# 1. Simple lookup (30 = 10 templates x 3 tenants)
# ---------------------------------------------------------------------------
_SIMPLE_LOOKUP_TEMPLATES = [
    ("How many suppliers does {t} have?", "SELECT count(*) FROM suppliers WHERE tenant_id = %s"),
    ("How many customers does {t} have?", "SELECT count(*) FROM customers WHERE tenant_id = %s"),
    ("How many plants does {t} operate?", "SELECT count(*) FROM plants WHERE tenant_id = %s"),
    ("How many products does {t} make?", "SELECT count(*) FROM products WHERE tenant_id = %s"),
    ("How many raw materials does {t} track?", "SELECT count(*) FROM materials WHERE tenant_id = %s"),
    ("How many purchase orders are currently open for {t}?", "SELECT count(*) FROM purchase_orders WHERE tenant_id = %s AND status = 'open'"),
    ("How many employees work at {t}?", "SELECT count(*) FROM employees WHERE tenant_id = %s"),
    ("How many warehouses does {t} have?", "SELECT count(*) FROM warehouses WHERE tenant_id = %s"),
    ("How many work orders are in progress for {t}?", "SELECT count(*) FROM work_orders WHERE tenant_id = %s AND status = 'in_progress'"),
    ("How many sales orders are open for {t}?", "SELECT count(*) FROM sales_orders WHERE tenant_id = %s AND status = 'open'"),
]


def _simple_lookup_questions(conn: psycopg.Connection, tenants: list[tuple[str, str]]) -> list[GoldenQuestion]:
    out = []
    for i, (tmpl, sql) in enumerate(_SIMPLE_LOOKUP_TEMPLATES):
        for tenant_name, tenant_id in tenants:
            result = _fetch_scalar(conn, sql, tenant_id)
            out.append(
                GoldenQuestion(
                    id=f"simple-{i:02d}-{tenant_name}",
                    category="simple_lookup",
                    tenant_name=tenant_name,
                    question=tmpl.format(t=tenant_name),
                    behavior="answer",
                    ground_truth_sql=sql,
                    expected_result=result,
                    notes="single-table count/lookup",
                )
            )
    return out


# ---------------------------------------------------------------------------
# 2. Metric definition (35 — exercises each of the 5 semantic-layer metrics)
# ---------------------------------------------------------------------------
_METRIC_TEMPLATES = {
    "material_yield_pct": (
        "What is {t}'s overall material yield percentage?",
        ("SELECT round(100.0 * sum(good_output) / nullif(sum(qty_input), 0), 1) "
        "FROM production_batches WHERE tenant_id = %s"),
    ),
    "scrap_rate_pct": (
        "What is {t}'s overall scrap rate percentage?",
        ("SELECT round(100.0 * sum(scrap_output) / nullif(sum(qty_input), 0), 1) "
        "FROM production_batches WHERE tenant_id = %s"),
    ),
    "revenue": (
        "What is {t}'s total revenue, excluding cancelled invoices?",
        "SELECT sum(amount) FROM invoices WHERE tenant_id = %s AND status != 'cancelled'",
    ),
    "quality_pass_rate_pct": (
        "What is {t}'s quality pass rate, excluding batches that were never inspected?",
        ("SELECT round(100.0 * count(*) FILTER (WHERE result = 'pass') / nullif(count(*) FILTER (WHERE result IS NOT NULL), 0), 1) "
        "FROM quality_checks WHERE tenant_id = %s"),
    ),
    "purchase_fill_rate_pct": (
        "What is {t}'s overall purchase order fill rate percentage?",
        ("SELECT round(100.0 * sum(coalesce(r.total_received, 0)) / nullif(sum(pol.qty_ordered), 0), 1) "
        "FROM purchase_order_lines pol "
        "LEFT JOIN (SELECT purchase_order_line_id, sum(qty_received) AS total_received FROM goods_receipts GROUP BY purchase_order_line_id) r "
        "ON r.purchase_order_line_id = pol.id WHERE pol.tenant_id = %s"),
    ),
}

_METRIC_VARIANT_PHRASINGS = [
    "What is {t}'s overall {label}?",
    "Can you tell me {t}'s {label}?",
    "What's the {label} for {t} across all plants?",
    "Report {t}'s {label}.",
    "Give me {t}'s current {label}.",
    "What is {t}'s {label} based on all recorded data?",
    "Summarize {t}'s {label}.",
]

_METRIC_LABELS = {
    "material_yield_pct": "material yield percentage",
    "scrap_rate_pct": "scrap rate percentage",
    "revenue": "total revenue (excluding cancelled invoices)",
    "quality_pass_rate_pct": "quality pass rate",
    "purchase_fill_rate_pct": "purchase order fill rate",
}


def _metric_definition_questions(conn: psycopg.Connection, tenants: list[tuple[str, str]]) -> list[GoldenQuestion]:
    out = []
    i = 0
    for metric_name, (_, sql) in _METRIC_TEMPLATES.items():
        for variant_idx in range(7):
            tenant_name, tenant_id = tenants[variant_idx % len(tenants)]
            phrasing = _METRIC_VARIANT_PHRASINGS[variant_idx]
            question = phrasing.format(t=tenant_name, label=_METRIC_LABELS[metric_name])
            result = _fetch_scalar(conn, sql, tenant_id)
            out.append(
                GoldenQuestion(
                    id=f"metric-{metric_name}-{variant_idx:02d}",
                    category="metric_definition",
                    tenant_name=tenant_name,
                    question=question,
                    behavior="answer",
                    ground_truth_sql=sql,
                    expected_result=result,
                    notes=f"exercises the {metric_name} semantic-layer metric definition",
                )
            )
            i += 1
    return out


# ---------------------------------------------------------------------------
# 3. Multi-table joins (30 = 10 templates x 3 tenants)
# ---------------------------------------------------------------------------
_YIELD_BY_SUPPLIER_SQL = """
WITH batch_supplier AS (
    SELECT pb.good_output, pb.qty_input,
        (SELECT po.supplier_id FROM goods_receipts gr
         JOIN purchase_order_lines pol ON pol.id = gr.purchase_order_line_id
         JOIN purchase_orders po ON po.id = pol.purchase_order_id
         WHERE pol.material_id = bi.material_id AND gr.received_date <= pb.produced_date
         ORDER BY gr.received_date DESC LIMIT 1) AS supplier_id
    FROM production_batches pb JOIN batch_inputs bi ON bi.production_batch_id = pb.id
    WHERE pb.tenant_id = %s
)
SELECT s.name, round(100.0 * sum(bs.good_output) / nullif(sum(bs.qty_input), 0), 1) AS yield_pct
FROM batch_supplier bs JOIN suppliers s ON s.id = bs.supplier_id
GROUP BY s.name ORDER BY yield_pct ASC LIMIT 1
"""


def _multi_join_questions(conn: psycopg.Connection, tenants: list[tuple[str, str]]) -> list[GoldenQuestion]:
    templates = [
        ("Which supplier's material gave the worst yield for {t}?", _YIELD_BY_SUPPLIER_SQL),
        (
            "List the top 3 customers by total order value for {t}.",
            ("SELECT c.name, sum(sol.qty_ordered * sol.unit_price) AS total_value "
            "FROM sales_order_lines sol JOIN sales_orders so ON so.id = sol.sales_order_id "
            "JOIN customers c ON c.id = so.customer_id WHERE sol.tenant_id = %s "
            "GROUP BY c.name ORDER BY total_value DESC LIMIT 3"),
        ),
        (
            "Which supplier has {t}'s best purchase order fill rate?",
            ("WITH r AS (SELECT purchase_order_line_id, sum(qty_received) AS total_received FROM goods_receipts GROUP BY purchase_order_line_id) "
            "SELECT s.name, round(100.0 * sum(coalesce(r.total_received,0)) / nullif(sum(pol.qty_ordered),0), 1) AS fill_pct "
            "FROM purchase_order_lines pol JOIN purchase_orders po ON po.id = pol.purchase_order_id "
            "JOIN suppliers s ON s.id = po.supplier_id LEFT JOIN r ON r.purchase_order_line_id = pol.id "
            "WHERE pol.tenant_id = %s GROUP BY s.name ORDER BY fill_pct DESC LIMIT 1"),
        ),
        (
            "Which employee has inspected the most quality checks for {t}?",
            ("SELECT e.name, count(*) AS n FROM quality_checks qc JOIN employees e ON e.id = qc.inspector_employee_id "
            "WHERE qc.tenant_id = %s GROUP BY e.name ORDER BY n DESC LIMIT 1"),
        ),
        (
            "What is the total quantity of goods received from each of {t}'s suppliers?",
            ("SELECT s.name, sum(gr.qty_received) FROM goods_receipts gr "
            "JOIN purchase_order_lines pol ON pol.id = gr.purchase_order_line_id "
            "JOIN purchase_orders po ON po.id = pol.purchase_order_id JOIN suppliers s ON s.id = po.supplier_id "
            "WHERE gr.tenant_id = %s GROUP BY s.name ORDER BY s.name LIMIT 5"),
        ),
        (
            "Which plant at {t} has produced the most finished product by volume?",
            ("SELECT pl.name, sum(pb.good_output) AS total FROM production_batches pb "
            "JOIN work_orders wo ON wo.id = pb.work_order_id JOIN plants pl ON pl.id = wo.plant_id "
            "WHERE pb.tenant_id = %s GROUP BY pl.name ORDER BY total DESC LIMIT 1"),
        ),
        (
            "How many invoices has {t} issued per customer region?",
            ("SELECT c.region, count(*) FROM invoices i JOIN sales_orders so ON so.id = i.sales_order_id "
            "JOIN customers c ON c.id = so.customer_id WHERE i.tenant_id = %s GROUP BY c.region ORDER BY c.region"),
        ),
        (
            "What is the average purchase order line value by supplier for {t}?",
            ("SELECT s.name, round(avg(pol.qty_ordered * pol.unit_price), 2) FROM purchase_order_lines pol "
            "JOIN purchase_orders po ON po.id = pol.purchase_order_id JOIN suppliers s ON s.id = po.supplier_id "
            "WHERE pol.tenant_id = %s GROUP BY s.name ORDER BY s.name LIMIT 5"),
        ),
        (
            "Which product has been sold to the most distinct customers for {t}?",
            ("SELECT p.name, count(DISTINCT so.customer_id) AS n_customers FROM sales_order_lines sol "
            "JOIN sales_orders so ON so.id = sol.sales_order_id JOIN products p ON p.id = sol.product_id "
            "WHERE sol.tenant_id = %s GROUP BY p.name ORDER BY n_customers DESC LIMIT 1"),
        ),
        (
            "How many production batches used material supplied by each of {t}'s suppliers?",
            ("WITH batch_supplier AS (SELECT pb.id, "
            "(SELECT po.supplier_id FROM goods_receipts gr JOIN purchase_order_lines pol ON pol.id = gr.purchase_order_line_id "
            "JOIN purchase_orders po ON po.id = pol.purchase_order_id "
            "WHERE pol.material_id = bi.material_id AND gr.received_date <= pb.produced_date "
            "ORDER BY gr.received_date DESC LIMIT 1) AS supplier_id "
            "FROM production_batches pb JOIN batch_inputs bi ON bi.production_batch_id = pb.id WHERE pb.tenant_id = %s) "
            "SELECT s.name, count(*) FROM batch_supplier bs JOIN suppliers s ON s.id = bs.supplier_id GROUP BY s.name ORDER BY s.name LIMIT 5"),
        ),
    ]
    out = []
    for i, (tmpl, sql) in enumerate(templates):
        for tenant_name, tenant_id in tenants:
            result = _fetch_all(conn, sql, (tenant_id,)) if "LIMIT 5" in sql or "LIMIT 3" in sql else _fetch_one(conn, sql, (tenant_id,))
            out.append(
                GoldenQuestion(
                    id=f"join-{i:02d}-{tenant_name}",
                    category="multi_table_join",
                    tenant_name=tenant_name,
                    question=tmpl.format(t=tenant_name),
                    behavior="answer",
                    ground_truth_sql=sql,
                    expected_result=result,
                    notes="requires 3+ table join",
                )
            )
    return out


# ---------------------------------------------------------------------------
# 4. Time logic (20 = ~7 templates spread across tenants)
# ---------------------------------------------------------------------------
_TIME_TEMPLATES = [
    (
        "What was {t}'s revenue in fiscal Q2 (Jul-Sep) 2026?",
        ("SELECT sum(amount) FROM invoices WHERE tenant_id = %s AND status != 'cancelled' "
        "AND invoice_date >= '2026-07-01' AND invoice_date <= '2026-09-30'"),
    ),
    (
        "How did {t}'s material yield trend over the last 6 months, by month?",
        ("SELECT date_trunc('month', produced_date) AS month, round(100.0*sum(good_output)/nullif(sum(qty_input),0),1) "
        "FROM production_batches WHERE tenant_id = %s AND produced_date >= current_date - interval '6 months' "
        "GROUP BY month ORDER BY month"),
    ),
    (
        "How many purchase orders did {t} place in each fiscal quarter?",
        ("SELECT CASE WHEN extract(month FROM order_date) IN (4,5,6) THEN 'Q1' "
        "WHEN extract(month FROM order_date) IN (7,8,9) THEN 'Q2' "
        "WHEN extract(month FROM order_date) IN (10,11,12) THEN 'Q3' ELSE 'Q4' END AS fy_q, count(*) "
        "FROM purchase_orders WHERE tenant_id = %s GROUP BY fy_q ORDER BY fy_q"),
    ),
    (
        "What was {t}'s total revenue in the most recent calendar month with any invoices?",
        ("SELECT sum(amount) FROM invoices WHERE tenant_id = %s AND status != 'cancelled' "
        "AND date_trunc('month', invoice_date) = (SELECT max(date_trunc('month', invoice_date)) FROM invoices WHERE tenant_id = %s)"),
    ),
    (
        "How many sales orders did {t} place in the last 90 days?",
        "SELECT count(*) FROM sales_orders WHERE tenant_id = %s AND order_date >= current_date - interval '90 days'",
    ),
    (
        "What was {t}'s scrap rate in fiscal Q1 (Apr-Jun) 2026 versus fiscal Q2?",
        ("SELECT CASE WHEN extract(month FROM produced_date) IN (4,5,6) THEN 'Q1' ELSE 'Q2' END AS fy_q, "
        "round(100.0*sum(scrap_output)/nullif(sum(qty_input),0),1) FROM production_batches "
        "WHERE tenant_id = %s AND produced_date >= '2026-04-01' AND produced_date <= '2026-09-30' GROUP BY fy_q ORDER BY fy_q"),
    ),
    (
        "How many goods receipts did {t} record year to date?",
        "SELECT count(*) FROM goods_receipts WHERE tenant_id = %s AND received_date >= date_trunc('year', current_date)",
    ),
]


def _time_logic_questions(conn: psycopg.Connection, tenants: list[tuple[str, str]]) -> list[GoldenQuestion]:
    out = []
    for i in range(20):
        tmpl, sql = _TIME_TEMPLATES[i % len(_TIME_TEMPLATES)]
        tenant_name, tenant_id = tenants[i % len(tenants)]
        params = (tenant_id, tenant_id) if sql.count("%s") == 2 else (tenant_id,)
        result = _fetch_all(conn, sql, params) if "GROUP BY" in sql else _fetch_one(conn, sql, params)
        out.append(
            GoldenQuestion(
                id=f"time-{i:02d}",
                category="time_logic",
                tenant_name=tenant_name,
                question=tmpl.format(t=tenant_name),
                behavior="answer",
                ground_truth_sql=sql,
                expected_result=result,
                notes="exercises fiscal-quarter / relative-date logic",
            )
        )
    return out


# ---------------------------------------------------------------------------
# 5. Ambiguous (15) — no single correct SQL; expected behavior is "clarify"
# ---------------------------------------------------------------------------
_AMBIGUOUS_QUESTIONS = [
    "Which of our plants is doing the best?",
    "How is our top supplier performing?",
    "Who is our best customer?",
    "What's our yield?",
    "How much did we spend with our main supplier?",
    "Is production on track?",
    "How are sales looking?",
    "What's the status of our biggest order?",
    "Which product should we focus on?",
    "How healthy is the supply chain right now?",
    "What's driving the numbers this period?",
    "Are we hitting our targets?",
    "How does this plant compare to the other one?",
    "What should we worry about?",
    "Give me the highlights.",
]


def _ambiguous_questions(tenants: list[tuple[str, str]]) -> list[GoldenQuestion]:
    out = []
    for i, q in enumerate(_AMBIGUOUS_QUESTIONS):
        tenant_name, _ = tenants[i % len(tenants)]
        out.append(
            GoldenQuestion(
                id=f"ambiguous-{i:02d}",
                category="ambiguous",
                tenant_name=tenant_name,
                question=q,
                behavior="clarify",
                ground_truth_sql=None,
                expected_result=None,
                notes="genuinely underspecified: which dimension/metric/entity is meant is not inferable",
            )
        )
    return out


# ---------------------------------------------------------------------------
# 6. Unanswerable (15) — the schema genuinely cannot answer these
# ---------------------------------------------------------------------------
_UNANSWERABLE_QUESTIONS = [
    ("Which purchase orders were delivered late?", "no due/promised-date field anywhere in the schema"),
    ("Which sales orders shipped late?", "no promised ship date field"),
    ("What's our employee turnover rate?", "no termination/end date on employees, only created_at"),
    ("What's the profit margin on each product?", "no manufacturing cost/BOM data, only sale and purchase unit prices"),
    ("What's our carbon footprint?", "not tracked anywhere in this schema"),
    ("Which customers are at risk of churning?", "no engagement/interaction/contact history data"),
    ("What's our employee satisfaction score?", "not tracked"),
    ("How many support tickets did we receive?", "no support/ticketing data in this schema"),
    ("What's the warranty claim rate on our products?", "no warranty/returns/claims data"),
    ("Who approved each purchase order?", "no approval/workflow data, only status"),
    ("What's our on-time delivery rate to customers?", "no promised delivery date field"),
    ("How much did we spend on marketing this year?", "no marketing/expense data in this schema"),
    ("What's the average employee tenure?", "no end-date/termination data to compute tenure"),
    ("Which suppliers offer the best payment terms?", "no payment-terms field on suppliers or purchase orders"),
    ("What's our inventory turnover ratio?", "stock_movements has no running balance; turnover needs point-in-time inventory levels not derivable without additional assumptions"),
]


def _unanswerable_questions(tenants: list[tuple[str, str]]) -> list[GoldenQuestion]:
    out = []
    for i, (q, reason) in enumerate(_UNANSWERABLE_QUESTIONS):
        tenant_name, _ = tenants[i % len(tenants)]
        out.append(
            GoldenQuestion(
                id=f"unanswerable-{i:02d}",
                category="unanswerable",
                tenant_name=tenant_name,
                question=q,
                behavior="unanswerable",
                ground_truth_sql=None,
                expected_result=None,
                notes=reason,
            )
        )
    return out


# ---------------------------------------------------------------------------
# 7. Messy wording (5) — same semantic content as a clean question, garbled phrasing
# ---------------------------------------------------------------------------
def _messy_wording_questions(conn: psycopg.Connection, tenants: list[tuple[str, str]]) -> list[GoldenQuestion]:
    items = [
        ("how many suppliers we got for {t}", "SELECT count(*) FROM suppliers WHERE tenant_id = %s"),
        ("wats total revenu for {t} not counting cancelled ones", "SELECT sum(amount) FROM invoices WHERE tenant_id = %s AND status != 'cancelled'"),
        ("gimme count of open POs 4 {t}", "SELECT count(*) FROM purchase_orders WHERE tenant_id = %s AND status = 'open'"),
        ("yield pct 4 {t} pls", "SELECT round(100.0*sum(good_output)/nullif(sum(qty_input),0),1) FROM production_batches WHERE tenant_id = %s"),
        ("how many custmers does {t} hav", "SELECT count(*) FROM customers WHERE tenant_id = %s"),
    ]
    out = []
    for i, (tmpl, sql) in enumerate(items):
        tenant_name, tenant_id = tenants[i % len(tenants)]
        result = _fetch_scalar(conn, sql, tenant_id)
        out.append(
            GoldenQuestion(
                id=f"messy-{i:02d}",
                category="messy_wording",
                tenant_name=tenant_name,
                question=tmpl.format(t=tenant_name),
                behavior="answer",
                ground_truth_sql=sql,
                expected_result=result,
                notes="deliberately garbled phrasing; same ground truth as the equivalent clean question",
            )
        )
    return out


def generate_golden_questions(conn: psycopg.Connection) -> list[GoldenQuestion]:
    tenants = _fetch_tenants(conn)
    if not tenants:
        raise RuntimeError("No tenants found — run scripts/seed_data.py first.")

    questions = (
        _simple_lookup_questions(conn, tenants)
        + _metric_definition_questions(conn, tenants)
        + _multi_join_questions(conn, tenants)
        + _time_logic_questions(conn, tenants)
        + _ambiguous_questions(tenants)
        + _unanswerable_questions(tenants)
        + _messy_wording_questions(conn, tenants)
    )

    # Hold out 40, spread proportionally across categories (every 15th/8th/
    # etc. isn't even across categories of very different sizes, so hold
    # out roughly the last ~27% of each category's own list instead of a
    # single global stride — keeps every category represented in both the
    # visible and held-out sets).
    by_category: dict[str, list[GoldenQuestion]] = {}
    for q in questions:
        by_category.setdefault(q.category, []).append(q)

    target_held_out = 40
    total = len(questions)
    held_out_count = 0
    for cat_questions in by_category.values():
        n_hold = round(len(cat_questions) * target_held_out / total)
        for q in cat_questions[-n_hold:] if n_hold else []:
            q.held_out = True
            held_out_count += 1

    # Reconcile rounding drift to land on exactly 40.
    all_sorted = questions
    while held_out_count < target_held_out:
        for q in all_sorted:
            if not q.held_out:
                q.held_out = True
                held_out_count += 1
                break
    while held_out_count > target_held_out:
        for q in reversed(all_sorted):
            if q.held_out:
                q.held_out = False
                held_out_count -= 1
                break

    return questions


def save(questions: list[GoldenQuestion], path: Path) -> None:
    path.write_text(json.dumps([asdict(q) for q in questions], indent=2, default=str))


def load(path: Path) -> list[GoldenQuestion]:
    data = json.loads(path.read_text())
    return [GoldenQuestion(**item) for item in data]
