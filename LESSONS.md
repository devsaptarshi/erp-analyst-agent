# Lessons

Real things that went wrong while building this, and what caught them.
Same spirit as `gatekeep-mcp`'s LESSONS.md — written for whoever (including
future me) builds the next project in this series.

## The dangerous-function blocklist was a silent no-op

The SQL validator is supposed to reject `set_config`, `pg_sleep`,
`dblink`, and a handful of other explicitly dangerous functions wherever
they appear in agent-generated SQL. The first version of this check did:

```python
fname = (func.sql_name() or getattr(func, "name", "") or "").lower()
```

That looked reasonable — try the "real" name, fall back to `.name` if
empty. It completely failed for exactly the functions it existed to
catch: `sqlglot` represents an unrecognized call like `set_config(...)`
as `exp.Anonymous`, and `exp.Anonymous.sql_name()` doesn't return empty —
it returns the literal string `"ANONYMOUS"`. That's truthy, so the `or`
chain locked onto it and the real function name in `.name` was never
consulted. Every "explicitly dangerous" function in the test suite passed
straight through, unblocked, in the very first test run.

The fix was a type check, not a smarter fallback:
`isinstance(func, exp.Anonymous)` → use `.name` directly. The general
lesson: a "truthy sentinel that isn't the value you wanted" defeats an
`or`-chain default silently — it won't error, won't warn, it'll just
quietly do the wrong thing forever unless something actually asserts the
blocked case fails to pass.

## Ordinary `WHERE a AND b` was rejected as an "unrecognized function"

Found by the first end-to-end test that used a real multi-condition
`WHERE` clause — nothing in the simpler, hand-written validator unit
tests happened to exercise more than one condition at a time. The
validator walks every `exp.Func` node and checks it against an allowlist;
it turns out `exp.And` and `exp.Or` are, in the installed `sqlglot`
version, subclasses of `exp.Func` (apparently an implementation detail of
how boolean connectors are modeled, not something documented as "this is
a function call"). So `WHERE x = 1 AND y = 2` walked `And` straight into
the "is this function on the allowlist?" check and failed it.

Not a security hole — the query was rejected, not wrongly allowed — but
it would have made the validator reject almost every real-world query the
moment it had more than one condition. The fix was a two-line exclusion;
the lesson is the same shape as the previous one: a type hierarchy from a
third-party library can put something in an unexpected category, and the
only way to find that is to actually run a realistic input through the
real library, not just reason about what "should" be in `exp.Func`.

## `date_trunc` and `CASE` tripped the same allowlist in a new way

While seeding real verified-query examples (Week 2), two more legitimate
query shapes got rejected by the SQL validator for the same underlying
reason as the `And`/`Or` bug above, but through different sqlglot nodes:

- `date_trunc('quarter', ...)` parses to `exp.TimestampTrunc`, whose
  `sql_name()` returns `"TIMESTAMP_TRUNC"` — not `"date_trunc"` — so it
  silently missed the `ALLOWED_FUNCTIONS` allowlist even though
  `date_trunc` itself was on it. Fixed by adding `"timestamp_trunc"` to
  the allowlist.
- `CASE`/`IF` expressions (needed for the fiscal-quarter business rule:
  the ERP's calendar year doesn't match its Q1-Q4 reporting quarters) are,
  like `And`/`Or`, modeled as `exp.Func` subclasses (`exp.Case`,
  `exp.If`) in this sqlglot version. Fixed the same way — extending the
  isinstance exclusion rather than trying to allowlist them by name.

Same lesson as above, found the same way: real queries against the real
library, not unit tests against the validator's intended behavior.

## A LangGraph node that skips setting a state key — the key still gets read later

The clarification-flow graph has a branch where `generate_sql_node`
decides the question needs clarification and doesn't produce real SQL. It
set `clarification_question` and left `sql` unset. That's fine until the
round-cap kicks in (`MAX_CLARIFY_ROUNDS`): the router then sends the state
to `validate_node` anyway, which unconditionally reads `state["sql"]` —
`KeyError`, only reachable once a question gets ambiguous enough to hit
the cap. Caught by
`test_clarification_is_capped_at_one_round_even_if_the_model_keeps_asking`,
not by the simpler happy-path clarify test, because the happy path never
drives state through every edge the router can actually take. Fixed by
always setting `"sql": generated.sql` (empty string on the clarifying
branch) so every node downstream of a conditional edge can rely on the
key existing regardless of which path got there. The general shape: a
`TypedDict`-based state machine's "optional" keys are only as optional as
the LEAST permissive node that reads them — audit by trawling every edge
a router can take, not just the one a hand-written scenario happens to
exercise.

## What this says about the testing strategy, not just the two bugs

Both bugs were caught by tests that exercise the REAL `sqlglot` parser and
(for the second one) the REAL LangGraph graph + REAL RLS-enforced
Postgres connection, with only the LLM call faked. Neither would have
been caught by a test that mocked `sqlglot` itself or asserted against the
validator's intended behavior in the abstract — both are exactly the kind
of gap between "what I wrote" and "what the library actually does with
real input" that only shows up when real input goes through the real
library. The pattern from `gatekeep-mcp`'s LESSONS.md repeats here: pure
business logic with no third-party parsing/protocol boundary was right on
the first pass (the schema, the RLS policies, the executor's control
flow); the two real bugs were both at a boundary with a library whose
internal type hierarchy wasn't in this project's control.
