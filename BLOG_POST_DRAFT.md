# Draft: "The `set_config` hole in text-to-SQL with RLS"

Status: **draft content only** — not published anywhere. Publishing is a
human action (choosing a platform, an account, a byline) outside what
this build environment does; this is the content to post, once the
held-out eval numbers below are filled in from a real run (see
KNOWN_LIMITS.md).

---

Most "secure" text-to-SQL agents stop at two defenses: validate the SQL
with an AST parser, and run it through a role with Row-Level Security.
That's not enough on its own, and the reason is a single Postgres
function: `set_config`.

If a generated query can call `set_config('app.tenant_id', '<any other
tenant>', true)` before its own `SELECT`, it can pick its own RLS context
— the validator has to specifically block it, by name, not just rely on
"RLS will catch anything bad." This project's `sql_validator.py` does
block it (`EXPLICITLY_DANGEROUS_FUNCTIONS`), but building that check
surfaced a quieter bug first: in the `sqlglot` version this project
pins, an unrecognized call like `set_config(...)` parses to
`exp.Anonymous`, and `exp.Anonymous.sql_name()` doesn't return empty —
it returns the literal string `"ANONYMOUS"`. A naive `fallback or
real_name` check locks onto that truthy sentinel and never looks at the
real function name. The very first test run proved every "blocked"
function sailed straight through, unblocked.

That's the shape of the whole project's real lesson: **validation and
RLS are not redundant, they're reinforcing** — a bug in one should never
be the only thing standing between a hostile query and another tenant's
data, and proving that took two independent layers plus tests that
exercise the REAL `sqlglot` parser and REAL Postgres RLS, not mocks of
either.

## What actually measures "is this good"

A single "it works on my example" demo doesn't say much. This project
instead:

- Built 150 golden questions with ground truth computed by actually
  running SQL against the seeded database — not hand-typed expected
  answers — with 40 held out and never looked at while building the
  agent or tuning prompts.
- Ran an A-E ablation: schema-only → +semantic layer → +verified-query
  retrieval → +result-check → +cheap/strong escalation, each pair
  compared with McNemar's paired significance test rather than just
  "accuracy went up."
- [Fill in once `scripts/ablation_eval.py` and the held-out run have
  actually executed against a live model: **[X]% accuracy on [N]
  held-out questions, zero tenant leaks across [M] attack tests**, and
  which of the five additions were statistically significant vs which
  weren't.]

## The CV line, once true

> Built a LangGraph text-to-SQL agent over a multi-tenant ERP with
> Postgres RLS, reaching [X]% accuracy on [N] held-out questions with
> zero tenant leaks across [M] attack tests.

## Sources

- [PostgreSQL row security policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [PostgreSQL system administration functions](https://www.postgresql.org/docs/current/functions-admin.html)
- [LangGraph interrupts, Python](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [A read-only SQL guard with sqlglot](https://dev.to/datanestdigital/a-read-only-sql-guard-for-llm-generated-queries-with-sqlglot-418j)
- [Why tenant context must be scoped per transaction](https://dev.to/m_zinger_2fc60eb3f3897908/why-tenant-context-must-be-scoped-per-transaction-3aop)
