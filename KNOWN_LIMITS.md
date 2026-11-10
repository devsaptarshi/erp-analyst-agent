# Known limits

- **Caching.** No query/result cache exists yet. If one is ever added, its
  key must include the full RLS-scoped context (tenant_id at minimum), not
  just the SQL text — a cached result keyed only on a query string can
  serve one tenant's data to another if the same SQL text happens to run
  for two different tenants. See `gatekeep-mcp`'s KNOWN_LIMITS.md for the
  same class of bug in a different project; this is the exact scenario
  that write-up is about.
- **No real ERP connection.** All data is synthetic (`scripts/seed_data.py`,
  fixed seed) — this never touches a real client's systems or data.
- **Read-only by design.** The agent has no write tool at the application
  layer, and `analyst_ro` has no INSERT/UPDATE/DELETE grants at the
  database layer either. Both would need to change for this to do
  anything beyond answering questions.
- **No real login system.** Tenant switching in the demo is not
  authentication — see the build spec's explicit scope cut. A real
  deployment needs its own session/auth layer in front of this.
