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
- **The held-out question set (40 of the 150 golden questions, never used
  while building the agent or tuning prompts) has not been run either.**
  Same blocker, same honest gap: no `ANTHROPIC_API_KEY`. This is the one
  the build spec asks for explicitly ("run the held-out questions once")
  as the final, unbiased accuracy number — the visible-question ablation
  above is for comparing configs against EACH OTHER, not for citing a
  headline accuracy, precisely because the same questions were visible
  while this was built. Don't skip straight to the CV-line number
  (README.md) without running this first.
- **The second model provider (OpenAI, via `langchain-openai`) is wired
  through `get_model()`/`Settings` but untested against a live OpenAI
  account** — no `OPENAI_API_KEY` was available either. `tests/unit/test_models.py`
  proves provider/tier selection constructs the right client with the
  right model id; it doesn't prove OpenAI's models actually produce
  usable SQL through this project's prompts, which were written and
  tuned entirely against Anthropic models.
- **The FastAPI backend's rate limiter estimates tokens from question
  length (`len(question) // 4`), not real Anthropic usage metadata** —
  because there's no live model call to get real usage from in this
  environment. `src/erp_analyst/api/limits.py`'s `estimate_cost_usd()`
  pricing table is also unverified against current list pricing; check
  before trusting any cost figure this produces.
- **Traces are a hand-rolled Postgres table (`src/erp_analyst/db/traces.py`),
  not Langfuse**, which the build spec's deployment table lists as the
  suggested option. Langfuse needs its own hosted project and API key,
  which this environment doesn't have; the hand-rolled version is real
  and tested (`tests/unit/test_tracing.py`, `tests/unit/test_api.py`) but
  lacks Langfuse's UI, cross-run analytics, and prompt-version tracking.
- **The Next.js frontend (`frontend/`) has been built (`npm run build`
  succeeds) but never run against a live backend** — no `ANTHROPIC_API_KEY`
  to actually answer a chat message through the real UI, and no browser
  in this environment to click through it even against a stubbed
  backend. The API it calls is unit-tested end to end with a fake model
  (`tests/unit/test_api.py`); the frontend's own request/response
  shapes match that API's Pydantic models by construction (same
  `ChatResponse` fields on both sides), but this is not the same as
  having watched it work in a browser.
- **The DB-dependent test suite (`tests/security/*`, `tests/unit/test_verified_queries.py`,
  the Postgres-checkpointer clarify test) could not be re-run at the end
  of this Week 3 session** — this container's Docker daemon was
  unreachable after a worker restart partway through the session (`docker
  compose up -d` failed with "Cannot connect to the Docker daemon"), and
  starting it required a sandbox bypass that was denied. These tests were
  passing earlier in this same session with a live Postgres (the Week 1/2
  commits cite exact pass counts run against one); only the newly-added
  Week 3 code — the FastAPI backend, tracing, rate limiter, second
  provider, confidence scoring — has been verified in THIS environment,
  via the subset of the suite that doesn't need Postgres (all fakeable
  with the same model/executor-faking pattern the rest of the project
  uses). Re-run the full suite with Postgres up before trusting the
  DB-dependent tests are still green after these changes.
- **Nothing in this repo has been deployed to a real host.** `DEPLOY.md`'s
  Dockerfiles and docker-compose config are written and
  `docker compose config`-validated, but this environment has no
  reachable Docker daemon (confirmed: `Cannot connect to the Docker
  daemon`) and no AWS/Vercel credentials, so no image has actually been
  built or run, and nothing has been pushed to AWS or Vercel.
- **The demo recording and the technical blog post are not produced by
  this repo** — see `DEMO.md` for the script and `BLOG_POST_DRAFT.md`
  for drafted content; actually recording a screen capture and
  publishing a post are human actions outside what this environment can
  do (no screen/browser to record, no blog platform credentials).
