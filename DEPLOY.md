# Deployment

This is written and compose/Dockerfile-validated (`docker compose config`
succeeds), but **not build-tested or deployed to any real host** — this
environment has no reachable Docker daemon and no AWS/Vercel credentials.
See [KNOWN_LIMITS.md](./KNOWN_LIMITS.md).

## Suggested hosting (per the build spec)

| Part | Suggestion |
| --- | --- |
| API | Docker on a small AWS EC2 server, or any container host |
| Database | Postgres with pgvector, seeded with fake data only |
| Frontend | Vercel |
| Traces | Langfuse, optional (this project ships a lighter hand-rolled trace table instead — see `src/erp_analyst/tracing.py` and `src/erp_analyst/db/traces.py` — because Langfuse needs its own hosted project/API key) |
| Abuse limits | Rate limit per IP, daily token ceiling, read-only demo (`src/erp_analyst/api/limits.py`) |

Check current pricing before choosing a host.

## Local run (what's actually been exercised)

```bash
docker compose up -d postgres
uv run python scripts/init_db.py
uv run python scripts/seed_data.py
uv run python scripts/seed_verified_queries.py   # hashing-trick embedder, no API key needed
uv sync
ANTHROPIC_API_KEY=sk-... uv run uvicorn erp_analyst.api.main:app --reload
```

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

## Full stack via Docker Compose (written, not run end-to-end here)

```bash
ANTHROPIC_API_KEY=sk-... docker compose up -d --build
uv run python scripts/init_db.py       # one-time, against the compose postgres on :5433
uv run python scripts/seed_data.py
```

Then the frontend is at `http://localhost:3000`, the API at
`http://localhost:8000`.

## Deploying for real

- **API**: push the image built from the root `Dockerfile` to any
  container host (EC2 + Docker, Fly.io, Render, Railway). Set
  `DATABASE_URL`, `ANALYST_DATABASE_URL`, and `ANTHROPIC_API_KEY` as
  environment variables, not baked into the image.
- **Frontend**: `frontend/` is a standard Next.js app — `vercel deploy`
  from that directory, with `NEXT_PUBLIC_API_URL` set to the deployed
  API's public URL in Vercel's project settings.
- **Database**: a managed Postgres with the pgvector extension available
  (e.g. AWS RDS does not support pgvector directly — use a pgvector-
  compatible host like Supabase, Neon, or a self-managed
  `pgvector/pgvector` image on a VM). Run `scripts/init_db.py` and
  `scripts/seed_data.py` once against it; never point this at anything
  but fake seeded data (see KNOWN_LIMITS.md — this is a portfolio demo,
  not a real ERP integration).
- **gatekeep-mcp's optional `ask_erp` upstream**: if demoing the two
  projects together, run the API first, then point gatekeep-mcp's
  `ERP_ANALYST_API_URL` env var at it before starting the gateway.
