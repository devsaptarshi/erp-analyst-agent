# erp-analyst-agent

A Python/LangGraph agent that answers plain-English analytics questions
over a **multi-tenant manufacturing ERP** — "which supplier's hides gave
the worst yield last quarter?" — with a hard requirement: it must never
leak one tenant's data into another, even when the question, the data, or
the SQL it writes is adversarial.

## Important: synthetic project, not a client deliverable

Everything in this repo — the schema, the data, the business rules — is
**designed from scratch and filled with fake data** (`src/erp_analyst/data/`,
`Faker` with a fixed seed). No table design, code, or data is copied from
any real ERP or real client work. This is a portfolio/interview project
built to close specific gaps (Python, LangGraph, applied ERP-domain
knowledge), not a production system or a client engagement.

## Why this is harder than a normal text-to-SQL demo

Text-to-SQL demos that look great on Spider-style benchmarks fall over on
two things real deployments can't skip: messy business meaning (what does
"on time" mean, which invoices count as revenue) and safe multi-tenant
access (a model that gets the tenant filter right 10,000 times can still
get it wrong on try 10,001 — see
[the AWS/PAR Technology write-up on exactly this problem](https://aws.amazon.com/blogs/machine-learning/multi-tenant-llm-analytics-with-row-level-security-how-we-built-a-secure-agent-on-aws/),
which this design follows closely).

So the security boundary here is **not** "ask the model nicely to filter
by tenant." It's three independent layers, each of which has to fail
before a cross-tenant leak is possible:

1. **Postgres Row-Level Security**, `FORCE`d, keyed on a tenant id that
   comes only from a verified server-side session — never from the model,
   the prompt, or anything the agent can influence.
2. **AST-based SQL validation** (`sqlglot`, never regex) — allowlisted
   tables/functions, single `SELECT` only, blocks `set_config`,
   `current_setting`, `pg_sleep`, `dblink`, and anything in the `pg_*`
   catalog, rejects unconditioned joins, wraps every query in an outer
   `LIMIT`.
3. **Application-layer discipline** — the agent is never given a write
   tool, the tenant id is bound server-side per request, raw DB errors are
   never shown to the model or the user.

See [SECURITY.md](./SECURITY.md) for the full threat model and
[KNOWN_LIMITS.md](./KNOWN_LIMITS.md) for what's explicitly out of scope.

## Status

Week 1 and Week 2 done — see the build spec for the three-week plan.
**146/146 tests pass.**

Week 1 delivered the security-critical core: synthetic multi-tenant data,
RLS, the AST-based SQL validator, the first working LangGraph agent
graph, and the Week 1 security test matrix (including a 1,000-request
connection-pool alternation test with zero cross-tenant leaks).

Week 2 built the parts that make answers actually good rather than just
safe: a versioned semantic layer (metrics/dimensions/business rules), a
pgvector verified-queries store for few-shot retrieval, a clarification
step via LangGraph's native `interrupt()` with `PostgresSaver` (survives
a process restart mid-interrupt — see
`tests/security/test_agent_clarify_postgres_checkpointer.py`), 150 golden
questions with ground truth computed from real seeded-data SQL runs (40
held out), a result-check repair step, cheap→strong model escalation on
repair, and a full A-E ablation harness with McNemar's paired
significance test to measure what each addition actually contributes.

See [LESSONS.md](./LESSONS.md) for the real bugs the tests caught along
the way — a silently-broken dangerous-function blocklist, `WHERE a AND b`
and `CASE`/`date_trunc` tripping the same sqlglot-allowlist issue in
different forms, and a LangGraph state key that was only "optional" on
the happy path.

The model-calling path itself (`real_sql_generator`) and the A-E
ablation harness are built and fully unit-tested with the model/DB calls
faked, but have not been run against a live model — no
`ANTHROPIC_API_KEY` was available while building this. See
[KNOWN_LIMITS.md](./KNOWN_LIMITS.md).

## Quickstart (dev)

```bash
uv sync
cp .env.example .env
docker compose up -d                 # Postgres 16 + pgvector on :5433
uv run python scripts/init_db.py     # schema, analyst_ro role, RLS policies
uv run python scripts/seed_data.py   # synthetic data for 3 tenants
uv run pytest                        # full suite, including the security test matrix
```
