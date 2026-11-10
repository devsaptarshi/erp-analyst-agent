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
- **The verified-queries store uses a hashing-trick embedder, not a real
  embedding model.** No embedding-provider API key (Voyage, OpenAI, etc.)
  was available while building this — see `src/erp_analyst/semantic/embeddings.py`
  for the full rationale and the exact technique (hashed character
  trigrams, L2-normalized). It's a real, testable retrieval signal — the
  retrieval-ranking tests prove it actually orders by similarity — but
  meaningfully weaker than a trained embedding model would be at telling
  apart two questions that mean the same thing but share few words. Swap
  `hashing_trick_embedder` for a real provider's client before trusting
  retrieval quality beyond what the tests directly assert.
- **`real_sql_generator` (the actual model-calling path) is untested
  against a live model.** No `ANTHROPIC_API_KEY` was available while
  building this — see `gatekeep-mcp`'s layer-2 eval for the same honest
  gap in the sibling project. Every control-flow test
  (`tests/unit/test_agent_graph.py`, `tests/security/test_agent_end_to_end.py`)
  drives the real LangGraph graph, the real validator, and (in the
  end-to-end tests) the real RLS-enforced Postgres connection, with only
  the model call itself faked. That proves the graph's routing and the
  security boundary; it does not prove a real model reliably produces
  parseable `​```sql` blocks, follows the schema correctly, or responds
  usefully to a repair prompt. Run `scripts/seed_data.py` then try a few
  real questions against `real_sql_generator` before trusting this beyond
  the faked tests.
- **No connection pooling in `TenantScopedExecutor` yet** — one new
  connection per request (see its docstring). Correct and safe, just not
  how a real deployment would want to handle load; the pool-alternation
  security test already proves the SET LOCAL-per-transaction pattern is
  pool-safe for whenever pooling is added.
- **The cartesian-join check rejects table-less `SELECT`s with a literal
  comma by coincidence of how sqlglot models commas** — only tested
  against real `FROM a, b` patterns, not exhaustively fuzzed against every
  way sqlglot might represent an implicit join.
- **The A-E ablation harness (`scripts/ablation_eval.py`) is built but has
  not been run.** It requires a real `ANTHROPIC_API_KEY` and a seeded
  Postgres instance to run all 5 configs (schema-only through
  +escalation) against the 110 visible golden questions and compute
  pairwise McNemar's tests between them — same honest gap as
  `real_sql_generator` above and `gatekeep-mcp`'s layer-2 eval. Everything
  it depends on is tested in isolation with the model/DB calls faked: the
  `allow_escalation`/`result_checker` graph toggles
  (`tests/unit/test_agent_graph_ablation_toggles.py`), the statistical
  test itself (`tests/unit/test_mcnemar.py`, including a hand-verified
  exact-binomial case), the scoring logic
  (`tests/unit/test_scoring.py`), and the result-checker's prompt/parsing
  (`tests/unit/test_result_check.py`). That proves the harness's logic is
  correct; it does not prove what the actual per-config accuracy numbers
  or significance results are. Run
  `ANTHROPIC_API_KEY=sk-... uv run python scripts/ablation_eval.py`
  against a seeded instance before citing any real A-E comparison.
