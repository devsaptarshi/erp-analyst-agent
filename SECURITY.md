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

Filled in as each control ships (tracked per-week in the task list).

| Threat | Control | Tested in |
|---|---|---|
| Model-generated SQL omits or forges the tenant filter | RLS enforces the real boundary regardless of what the generated SQL does | `tests/security/` |
| `set_config('app.tenant_id', ...)` smuggled into generated SQL to impersonate another tenant | sqlglot validator blocks `set_config`/`current_setting` outright | `tests/security/` |
| A session's tenant context leaking to the next request in a pooled connection | `SET LOCAL` (transaction-scoped, not session-scoped) for `app.tenant_id` on every request | `tests/security/` |
| Expensive/runaway query (DoS) | 5s statement timeout (role default + per-request), `EXPLAIN`-based cost rejection, outer `LIMIT` wrap | `tests/security/` |
| Writes via the analyst path | No write tool at the app layer; `analyst_ro` has SELECT-only grants | manual verification (see README) + `tests/security/` |
