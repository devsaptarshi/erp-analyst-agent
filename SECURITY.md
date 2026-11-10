# Security model

## Boundary

Three independent layers, each of which must fail before a cross-tenant
leak is possible:

1. **Postgres Row-Level Security** — `FORCE`d on every tenant-scoped
   table (and on `tenants` itself), keyed on
   `current_setting('app.tenant_id', true)`. Enforced by Postgres, not by
   application code, so it holds even if the SQL validator or the agent
   logic has a bug. See `src/erp_analyst/db/rls.sql`.
2. **AST-based SQL validation** (`sqlglot`) before any query reaches the
   database — never regex. See `src/erp_analyst/validation/`.
3. **Application discipline** — the agent is never given a write tool,
   `tenant_id` is set from a verified server-side session only (never from
   the model, the prompt, or user-controllable input), raw database errors
   are never surfaced to the model or the user.

## Threat table

| Threat | Control | Tested in |
|---|---|---|
| Model-generated SQL omits or forges the tenant filter | RLS enforces the real boundary regardless of what the generated SQL does | `test_each_tenant_sees_only_its_own_canary_row`, `test_the_planted_yield_fact_is_answerable_end_to_end_through_the_real_graph` |
| `set_config`/`current_setting` smuggled into generated SQL to impersonate another tenant | sqlglot validator blocks both outright, even mid-expression (e.g. `... OR set_config(...) IS NOT NULL`) | `test_set_config_impersonation_attempts_are_rejected_before_reaching_postgres` |
| A tenant's context leaking into the next request on a pooled connection | `set_config(..., true)` (transaction-scoped, equivalent to `SET LOCAL`) applied fresh on every request, never session-scoped | `test_1000_request_pool_alternation_never_leaks` — 1,000 real requests through a real `ConnectionPool`, alternating tenants, zero leaks |
| No tenant context set at all (a bug elsewhere forgot to set it) | RLS fails closed — zero rows, not "all rows" | `test_direct_rls_with_no_tenant_context_returns_zero_rows` |
| A crafted `WHERE` clause trying to read another tenant by id | RLS applies regardless of the query's own predicates | `test_direct_rls_cannot_be_overridden_by_a_crafted_where_clause` |
| Writes via the analyst path | No write tool at the app layer; `analyst_ro` has SELECT-only grants, confirmed to get "permission denied" | `test_analyst_ro_cannot_write`, `test_write_ddl_and_multi_statement_attempts_never_reach_postgres` |
| `analyst_ro` trying to lift its own RLS exemption | No `ALTER TABLE` rights | `test_analyst_ro_cannot_bypass_rls_even_with_superuser_style_tricks` |
| Multi-statement / DDL / `COPY` smuggled after a semicolon | sqlglot rejects anything parsing to more than one statement, or to a non-`SELECT` type | `test_write_ddl_and_multi_statement_attempts_never_reach_postgres`, `test_non_select_statements_are_rejected` |
| Cartesian-product join (explicit `CROSS JOIN` or an implicit comma-separated `FROM`) | Every `JOIN` node must carry an `ON`/`USING` condition | `test_a_comma_separated_from_list_is_rejected_as_an_unconditioned_join`, `test_an_unconditioned_cross_join_across_large_tables_is_rejected_before_execution` |
| Expensive/runaway query (DoS) | 5s statement timeout (role default + per-request `SET LOCAL`), `EXPLAIN`-based cost estimate, outer `LIMIT` wrap/cap | `test_estimate_cost_is_higher_for_an_unindexed_cross_table_scan_than_a_simple_lookup`, `test_a_query_with_a_limit_over_the_max_is_capped` |
| SQL-injection-shaped text stored as ordinary data (a name with a stray quote) | Parameterized queries never re-interpret stored data as SQL, regardless of its contents | `test_injection_looking_text_stored_as_data_is_inert_and_still_tenant_scoped` |
| Raw DB errors leaking schema/internal details to the model or user | Executor catches `psycopg.Error`, logs the real one, returns a generic one | `src/erp_analyst/db/executor.py` (code-level; no test currently asserts the generic-vs-raw distinction directly — tracked as a gap) |

Two real validator bugs were found by tests in this repo, not by manual
review — see `LESSONS.md` for the full account:
1. `set_config`/`pg_sleep`/etc. were silently **not** being blocked at
   all, because sqlglot represents an unrecognized call as `exp.Anonymous`
   whose `.sql_name()` returns the literal sentinel `"ANONYMOUS"` rather
   than the real function name.
2. Ordinary `WHERE a AND b` was being rejected as an unrecognized
   "function", because sqlglot's `exp.And`/`exp.Or` are (surprisingly)
   subclasses of `exp.Func` in the installed version.

Both are fixed and covered by regression tests; both are the kind of
thing a confident-sounding but untested "the validator blocks dangerous
functions" claim would have missed entirely.
