#!/usr/bin/env python3
"""One-time (idempotent) setup: schema, the analyst_ro role, and RLS
policies. Run as the admin user (settings.database_url), never as
analyst_ro — analyst_ro has no DDL rights by design.
"""
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from erp_analyst.config import settings

SCHEMA_SQL = (Path(__file__).resolve().parent.parent / "src/erp_analyst/db/schema.sql").read_text()
RLS_SQL = (Path(__file__).resolve().parent.parent / "src/erp_analyst/db/rls.sql").read_text()


def analyst_role_password() -> str:
    """Pulled from ANALYST_DATABASE_URL so the password lives in exactly
    one place (the .env file), never duplicated or hardcoded in SQL."""
    parsed = urlparse(settings.analyst_database_url)
    if not parsed.password:
        raise SystemExit("ANALYST_DATABASE_URL must include a password for the analyst_ro role.")
    return parsed.password


def main() -> None:
    password = analyst_role_password()

    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'analyst_ro'")
            exists = cur.fetchone() is not None
            if exists:
                # NOSUPERUSER / NOCREATEDB / NOCREATEROLE / NOBYPASSRLS are
                # the defaults for a new role, but stated explicitly on
                # both create and alter so a future `CREATE ROLE
                # analyst_ro SUPERUSER` elsewhere in a real deployment
                # can't silently widen this role without this script
                # re-asserting the narrow grant on its next run.
                cur.execute(
                    sql.SQL(
                        "ALTER ROLE analyst_ro WITH LOGIN PASSWORD {} "
                        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"
                    ).format(sql.Literal(password))
                )
                print("analyst_ro role already existed — password/attributes re-asserted.")
            else:
                cur.execute(
                    sql.SQL(
                        "CREATE ROLE analyst_ro WITH LOGIN PASSWORD {} "
                        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"
                    ).format(sql.Literal(password))
                )
                print("Created analyst_ro role.")

        print("Applying schema...")
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)

        print("Applying RLS policies...")
        with conn.cursor() as cur:
            cur.execute(RLS_SQL)

    print("Done.")


if __name__ == "__main__":
    main()
