import sys
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from erp_analyst.config import settings


@pytest.fixture(scope="session")
def admin_conn():
    """Admin connection — DDL rights. Only use this to set up test fixtures
    (e.g. canary rows), never to exercise the agent's own read path."""
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        yield conn


@pytest.fixture
def analyst_conn():
    """A fresh analyst_ro connection per test, with no tenant context set
    (tests must SET LOCAL app.tenant_id themselves) and in a transaction
    that's always rolled back, so tests never see each other's SET LOCAL
    context leak across tests."""
    with psycopg.connect(settings.analyst_database_url, autocommit=False) as conn:
        yield conn
        conn.rollback()


@pytest.fixture(scope="session")
def tenant_ids(admin_conn) -> dict[str, str]:
    """Maps tenant name -> id, for the data seeded by scripts/seed_data.py.
    Tests depend on that script having been run first (see README / CI)."""
    with admin_conn.cursor() as cur:
        cur.execute("SELECT name, id FROM tenants ORDER BY name")
        rows = cur.fetchall()
    if not rows:
        pytest.skip("No tenants found — run `uv run python scripts/seed_data.py` first.")
    return {name: str(tid) for name, tid in rows}


def set_tenant(conn: psycopg.Connection, tenant_id: str) -> None:
    """Sets the RLS tenant context for the CURRENT transaction only, so a
    pooled connection never carries one request's tenant context into the
    next. `SET LOCAL x = $1` is not valid Postgres syntax (SET's value
    position doesn't accept a bind parameter) — `set_config(name, value,
    is_local)` is the parameterizable equivalent, with `is_local=true`
    giving the same transaction-scoped behavior as SET LOCAL. This is the
    ONE place in the whole codebase allowed to call set_config: it's on
    the trusted application's own connection-setup path, never inside SQL
    the model generates — the validator explicitly blocks `set_config` in
    agent-authored SQL for exactly this reason (src/erp_analyst/validation/sql_validator.py).
    """
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
