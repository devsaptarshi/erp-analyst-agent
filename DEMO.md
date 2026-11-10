# Demo script

One great answer, one honest refusal, one failed attack — under two
minutes. Not yet recorded (no screen/browser in this build environment —
see KNOWN_LIMITS.md); this is the script to record it from.

Prerequisites: `docker compose up -d postgres`, `scripts/init_db.py`,
`scripts/seed_data.py`, the API running with a real `ANTHROPIC_API_KEY`,
the frontend running and pointed at it.

1. **Log in as Acme Leather Co** (the tenant switcher in the top bar) and
   ask: *"Which supplier's hides gave the worst yield last quarter?"*
   Show the answer, the bar chart, and the generated SQL (the "Show SQL"
   toggle). Expected: **Northline Hides**, ~65.7% yield in the planted bad
   quarter — the project's own flagship question (see
   `scripts/seed_data.py`'s `PLANTED_BAD_SUPPLIER_NAME`).
2. Ask: *"Who are our top customers?"* The agent should ask whether you
   mean by revenue or by volume — the clarification flow
   (`agent/graph.py`'s `clarify` node). Answer "by revenue" and show it
   resuming the SAME conversation thread with a real answer.
3. Ask something the data genuinely can't answer (e.g. a question about a
   dimension not in the schema, like delivery due dates — see the
   semantic layer's `no_delivery_due_dates` business rule). The agent
   should say so honestly rather than guess.
4. Switch to Tenant B (Summit Tanning Works) and try asking for Tenant A's
   revenue by name. No cross-tenant data comes back — RLS enforces this
   independently of whatever the model does.
5. Show the same class of attack in the test suite —
   `tests/security/test_tenant_isolation.py` — then the results table
   (once the held-out eval and ablation have actually been run; see
   KNOWN_LIMITS.md for why that hasn't happened yet in this build).

## Recording checklist

- [ ] Screen capture at a legible resolution, under 2 minutes
- [ ] Captions or voiceover naming each step as it happens
- [ ] Cut from step 5's test suite to the results table rather than
      scrolling a terminal live
