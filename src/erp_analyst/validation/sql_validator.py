"""AST-based SQL validation via sqlglot — never regex. This is the second
of three independent defense layers (see SECURITY.md); Postgres RLS is the
authoritative one and holds even if a bug here lets something through.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

DIALECT = "postgres"

ALLOWED_TABLES = frozenset(
    {
        "tenants", "plants", "suppliers", "customers", "products", "materials", "employees",
        "purchase_orders", "purchase_order_lines", "goods_receipts",
        "work_orders", "production_batches", "batch_inputs", "quality_checks",
        "warehouses", "stock_movements",
        "sales_orders", "sales_order_lines", "invoices", "payments",
    }
)

# Explicit, generous-but-bounded allowlist for analytics SQL. Anything not
# here is rejected, even if it's harmless — the point of an allowlist is
# that additions are a deliberate decision, not an oversight.
ALLOWED_FUNCTIONS = frozenset(
    {
        "count", "sum", "avg", "min", "max", "round", "coalesce", "nullif",
        "date_trunc", "extract", "now", "current_date", "age",
        "to_char", "lower", "upper", "trim", "concat", "length", "substring",
        "abs", "ceil", "floor", "greatest", "least", "cast",
        "array_agg", "string_agg", "percentile_cont", "percentile_disc",
        "rank", "dense_rank", "row_number", "lag", "lead", "sum_filter",
        "stddev", "variance", "generate_series",
    }
)

# Named explicitly (even though they'd already fail the allowlist check)
# so a rejection message says WHY this one is dangerous, not just "not on
# the list" — the difference matters for anyone reading a rejected query's
# logs later.
EXPLICITLY_DANGEROUS_FUNCTIONS = frozenset(
    {
        "set_config", "current_setting", "pg_sleep", "pg_sleep_for", "pg_sleep_until",
        "dblink", "dblink_connect", "dblink_exec",
        "lo_import", "lo_export", "pg_read_file", "pg_read_binary_file",
        "pg_ls_dir", "pg_stat_file", "query_to_xml",
    }
)

DISALLOWED_STATEMENT_TYPES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.TruncateTable, exp.Grant, exp.Set, exp.Command, exp.Merge,
)

DEFAULT_MAX_LIMIT = 1000


@dataclass
class ValidationResult:
    ok: bool
    sql: str | None = None  # the rewritten (LIMIT-wrapped) SQL, if ok
    errors: list[str] = field(default_factory=list)


def validate(raw_sql: str, max_limit: int = DEFAULT_MAX_LIMIT) -> ValidationResult:
    errors: list[str] = []

    try:
        statements = [s for s in sqlglot.parse(raw_sql, dialect=DIALECT) if s is not None]
    except Exception as exc:  # noqa: BLE001 — sqlglot raises several undocumented exception types on malformed SQL; this validator must never crash, only reject
        return ValidationResult(ok=False, errors=[f"SQL failed to parse: {exc}"])

    if len(statements) == 0:
        return ValidationResult(ok=False, errors=["No SQL statement found."])
    if len(statements) > 1:
        return ValidationResult(ok=False, errors=[f"Only one statement is allowed; found {len(statements)}."])

    stmt = statements[0]

    if not isinstance(stmt, (exp.Select,)):
        return ValidationResult(ok=False, errors=[f"Only a single SELECT statement is allowed; got {type(stmt).__name__}."])

    for node in stmt.walk():
        node_obj = node[0] if isinstance(node, tuple) else node
        if isinstance(node_obj, DISALLOWED_STATEMENT_TYPES):
            return ValidationResult(ok=False, errors=[f"Disallowed statement type: {type(node_obj).__name__}."])

    cte_names = {cte.alias.lower() for cte in stmt.find_all(exp.CTE) if cte.alias}

    for table in stmt.find_all(exp.Table):
        name = table.name.lower()
        if name and name not in ALLOWED_TABLES and name not in cte_names:
            errors.append(f'Table "{name}" is not on the allowlist.')

    for func in stmt.find_all(exp.Func):
        # sqlglot's exp.And / exp.Or (boolean connectors in a WHERE/ON
        # clause) are, surprisingly, subclasses of exp.Func in this
        # version — found by an end-to-end test using a real multi-
        # condition WHERE clause, which every hand-written validator unit
        # test up to that point happened not to exercise. Without this
        # exclusion, ordinary `a AND b` in a WHERE clause would be rejected
        # as an unrecognized "function" — not a security hole, but it
        # would have made the validator reject almost every real query.
        if isinstance(func, (exp.And, exp.Or)):
            continue

        # sqlglot gives named/recognized functions (count, sum, ...) a real
        # `.sql_name()`. An unrecognized call like set_config(...) parses
        # as exp.Anonymous, whose `.sql_name()` returns the sentinel
        # string "ANONYMOUS" — the actual name is in `.name` instead. That
        # sentinel is truthy, so it must be special-cased rather than used
        # as a fallback-chain default (an `or` chain would just keep it).
        if isinstance(func, exp.Anonymous):
            fname = (func.name or "").lower()
        else:
            fname = (func.sql_name() or "").lower()
        if not fname:
            continue
        if fname in EXPLICITLY_DANGEROUS_FUNCTIONS:
            errors.append(f'Function "{fname}" is explicitly blocked — it can affect session state, the filesystem, or timing.')
        elif fname not in ALLOWED_FUNCTIONS:
            errors.append(f'Function "{fname}" is not on the allowlist.')

    for join in stmt.find_all(exp.Join):
        if join.args.get("on") is None and not join.args.get("using"):
            errors.append("A join with no ON/USING condition is not allowed (cartesian-product risk), including a comma-separated FROM list.")

    if errors:
        return ValidationResult(ok=False, errors=errors)

    rewritten = _enforce_limit(stmt, max_limit)
    return ValidationResult(ok=True, sql=rewritten.sql(dialect=DIALECT))


def estimate_cost(conn, sql: str) -> float:
    """Runs EXPLAIN (FORMAT JSON) and returns the planner's estimated
    total cost. Requires an already-validated, already-LIMIT-wrapped
    query and a live connection — this is a runtime check, not a pure AST
    one, since only the real planner (with real table statistics) can
    estimate cost. Call this AFTER validate() and BEFORE executing the
    real query, inside the same read-only, tenant-scoped transaction.
    """
    import json

    with conn.cursor() as cur:
        cur.execute(f"EXPLAIN (FORMAT JSON) {sql}")
        (plan_json,) = cur.fetchone()
    plan = json.loads(plan_json) if isinstance(plan_json, str) else plan_json
    return float(plan[0]["Plan"]["Total Cost"])


def _enforce_limit(stmt: exp.Select, max_limit: int) -> exp.Select:
    existing = stmt.args.get("limit")
    if existing is None:
        return stmt.limit(max_limit)
    try:
        existing_value = int(existing.expression.this)
    except (AttributeError, TypeError, ValueError):
        return stmt.limit(max_limit)
    if existing_value > max_limit:
        return stmt.limit(max_limit)
    return stmt
