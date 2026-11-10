#!/usr/bin/env python3
"""Seeds the verified_queries store with known-good (question, SQL) pairs
covering the schema's trickiest patterns — the ones a model is most
likely to get wrong without an example (see SECURITY.md / the semantic
layer's business_rules for why each of these is tricky).
"""
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from erp_analyst.config import settings
from erp_analyst.db.verified_queries import add, init_table
from erp_analyst.semantic.embeddings import hashing_trick_embedder

EXAMPLES: list[tuple[str, str, list[str]]] = [
    (
        "Which supplier's material gave the worst yield last quarter?",
        """WITH batch_supplier AS (
    SELECT pb.good_output, pb.qty_input,
        (SELECT po.supplier_id FROM goods_receipts gr
         JOIN purchase_order_lines pol ON pol.id = gr.purchase_order_line_id
         JOIN purchase_orders po ON po.id = pol.purchase_order_id
         WHERE pol.material_id = bi.material_id AND gr.received_date <= pb.produced_date
         ORDER BY gr.received_date DESC LIMIT 1) AS supplier_id
    FROM production_batches pb JOIN batch_inputs bi ON bi.production_batch_id = pb.id
)
SELECT s.name, round(100.0 * sum(bs.good_output) / nullif(sum(bs.qty_input), 0), 1) AS yield_pct
FROM batch_supplier bs JOIN suppliers s ON s.id = bs.supplier_id
GROUP BY s.name ORDER BY yield_pct ASC""",
        ["yield", "supplier", "multi-hop-join"],
    ),
    (
        "What was total revenue last month?",
        "SELECT sum(amount) FROM invoices WHERE status != 'cancelled' AND invoice_date >= date_trunc('month', current_date) - interval '1 month' AND invoice_date < date_trunc('month', current_date)",
        ["revenue", "cancelled-exclusion"],
    ),
    (
        "How much material did we receive from each supplier, in kg, ignoring lines recorded in other units?",
        ("SELECT s.name, sum(gr.qty_received) FROM goods_receipts gr "
        "JOIN purchase_order_lines pol ON pol.id = gr.purchase_order_line_id "
        "JOIN purchase_orders po ON po.id = pol.purchase_order_id "
        "JOIN suppliers s ON s.id = po.supplier_id "
        "WHERE pol.unit = 'kg' GROUP BY s.name"),
        ["unit-mismatch"],
    ),
    (
        "What's our purchase order fill rate by supplier?",
        """WITH received_per_line AS (
    SELECT purchase_order_line_id, sum(qty_received) AS total_received
    FROM goods_receipts GROUP BY purchase_order_line_id
)
SELECT s.name, round(100.0 * sum(coalesce(r.total_received, 0)) / nullif(sum(pol.qty_ordered), 0), 1) AS fill_rate_pct
FROM purchase_order_lines pol
JOIN purchase_orders po ON po.id = pol.purchase_order_id
JOIN suppliers s ON s.id = po.supplier_id
LEFT JOIN received_per_line r ON r.purchase_order_line_id = pol.id
GROUP BY s.name""",
        ["fill-rate", "left-join-coalesce"],
    ),
    (
        "How much have we bought from Shanti Tanning, including all the ways their name is spelled?",
        ("SELECT sum(pol.qty_ordered) FROM purchase_order_lines pol "
        "JOIN purchase_orders po ON po.id = pol.purchase_order_id "
        "JOIN suppliers s ON s.id = po.supplier_id "
        "WHERE s.name ILIKE 'Shanti Tanning%'"),
        ["name-variants", "supplier"],
    ),
    (
        "What's our quality pass rate, not counting batches that were never inspected?",
        ("SELECT round(100.0 * count(*) FILTER (WHERE result = 'pass') / nullif(count(*) FILTER (WHERE result IS NOT NULL), 0), 1) "
        "FROM quality_checks"),
        ["quality", "missing-data"],
    ),
    (
        "Revenue by financial-year quarter this year",
        ("SELECT CASE "
        "WHEN extract(month FROM invoice_date) IN (4,5,6) THEN 'Q1' "
        "WHEN extract(month FROM invoice_date) IN (7,8,9) THEN 'Q2' "
        "WHEN extract(month FROM invoice_date) IN (10,11,12) THEN 'Q3' "
        "ELSE 'Q4' END AS fy_quarter, sum(amount) "
        "FROM invoices WHERE status != 'cancelled' GROUP BY fy_quarter ORDER BY fy_quarter"),
        ["quarter-definition", "fiscal-year"],
    ),
    (
        "List our top 5 customers by total order value",
        ("SELECT c.name, sum(sol.qty_ordered * sol.unit_price) AS total_value "
        "FROM sales_order_lines sol "
        "JOIN sales_orders so ON so.id = sol.sales_order_id "
        "JOIN customers c ON c.id = so.customer_id "
        "GROUP BY c.name ORDER BY total_value DESC LIMIT 5"),
        ["ranking", "simple-join"],
    ),
]


def main() -> None:
    with psycopg.connect(settings.database_url, autocommit=False) as conn:
        init_table(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM verified_queries")
            (existing,) = cur.fetchone()
        if existing > 0:
            print(f"verified_queries already has {existing} rows — skipping (delete rows first to reseed).")
            return
        for question, sql, tags in EXAMPLES:
            add(conn, question, sql, hashing_trick_embedder, tags)
        print(f"Seeded {len(EXAMPLES)} verified queries.")


if __name__ == "__main__":
    main()
