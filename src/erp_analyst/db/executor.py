"""Executes already-validated SQL against the analyst_ro role, inside a
READ ONLY, tenant-scoped transaction. This is where layers 1 (RLS) and 2
(sqlglot validation) meet layer 3 (application discipline): tenant_id
here comes from the caller's own verified argument, never parsed out of
the SQL text or the model's own words.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import psycopg

from erp_analyst.config import settings
from erp_analyst.validation.sql_validator import validate

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    ok: bool
    rows: list[dict[str, Any]] | None = None
    columns: list[str] | None = None
    error: str | None = None


class TenantScopedExecutor:
    """One instance per request/question — opens its own connection so a
    tenant's context can never leak into a pooled connection reused by a
    different tenant's request. (A real deployment with high QPS would
    want a connection pool with SET LOCAL re-applied per checkout, not
    per-request connections — see KNOWN_LIMITS.md.)
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    def execute(self, raw_sql: str) -> ExecutionResult:
        validation = validate(raw_sql)
        if not validation.ok:
            return ExecutionResult(ok=False, error="; ".join(validation.errors))

        try:
            with psycopg.connect(settings.analyst_database_url, autocommit=False) as conn:
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                    cur.execute(f"SET LOCAL statement_timeout = {int(settings.analyst_statement_timeout_ms)}")
                    # set_config, not SET LOCAL directly — see
                    # tests/conftest.py's set_tenant() docstring for why
                    # SET LOCAL can't take a bind parameter. This is the
                    # application's own trusted connection-setup code, the
                    # one place allowed to call it (never agent SQL).
                    cur.execute("SELECT set_config('app.tenant_id', %s, true)", (self.tenant_id,))
                    cur.execute(validation.sql)  # the VALIDATED, LIMIT-wrapped SQL — never the raw input
                    columns = [d.name for d in cur.description] if cur.description else []
                    rows = [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]
                conn.rollback()  # belt and braces: READ ONLY already forbids writes, but never commit either
            return ExecutionResult(ok=True, rows=rows, columns=columns)
        except psycopg.Error as exc:
            # Never surface the raw DB error to the model or the user —
            # it can carry schema details or hint at the bypass that
            # almost worked. Log the real one; return a generic one.
            logger.warning("Query execution failed for tenant %s: %s", self.tenant_id, exc)
            return ExecutionResult(ok=False, error=f"Query failed: {type(exc).__name__}")
