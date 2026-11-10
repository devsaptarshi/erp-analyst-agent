"""The HTTP surface the Next.js frontend talks to. Everything that needs
a live service (the graph's model calls, Postgres) is injected into
`create_app()` with real defaults, so tests can swap in fakes the same
way the rest of this project's unit tests fake the model/executor —
importing this module never opens a real connection; only calling
`create_app()` with no overrides does.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any, Literal

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from langgraph.types import Command
from pydantic import BaseModel

from erp_analyst.agent.graph import build_graph
from erp_analyst.agent.result_check import make_result_checker
from erp_analyst.agent.sql_generation import make_sql_generator
from erp_analyst.api.limits import RateLimiter
from erp_analyst.config import settings
from erp_analyst.db.executor import TenantScopedExecutor
from erp_analyst.db.traces import PostgresTraceStore, Trace, TraceStore
from erp_analyst.semantic.loader import SemanticLayer
from erp_analyst.tracing import run_with_timings

TenantResolver = Callable[[str], str | None]
TenantLister = Callable[[], list[str]]


class ChatRequest(BaseModel):
    question: str
    tenant_name: str
    thread_id: str | None = None


class ChatResponse(BaseModel):
    trace_id: str
    thread_id: str
    answer: str | None = None
    sql: str | None = None
    rows: list[dict] | None = None
    confidence: str | None = None
    clarification_question: str | None = None


class ResumeRequest(BaseModel):
    thread_id: str
    answer: str


class FeedbackRequest(BaseModel):
    trace_id: str
    vote: Literal["up", "down"]


def _default_tenant_resolver(tenant_name: str) -> str | None:
    with psycopg.connect(settings.database_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM tenants WHERE name = %s", (tenant_name,))
        row = cur.fetchone()
    return str(row[0]) if row else None


def _default_tenant_lister() -> list[str]:
    with psycopg.connect(settings.database_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT name FROM tenants ORDER BY name")
        return [r[0] for r in cur.fetchall()]


def _default_graph():
    from langgraph.checkpoint.postgres import PostgresSaver

    semantic_layer = SemanticLayer.load()
    sql_generator = make_sql_generator(semantic_layer=semantic_layer)
    result_checker = make_result_checker()
    checkpointer = PostgresSaver.from_conn_string(settings.database_url)
    checkpointer.setup()
    return build_graph(
        sql_generator=sql_generator,
        executor_factory=TenantScopedExecutor,
        checkpointer=checkpointer,
        allow_escalation=True,
        result_checker=result_checker,
    )


def create_app(
    graph: Any = None,
    tenant_resolver: TenantResolver | None = None,
    tenant_lister: TenantLister | None = None,
    trace_store: TraceStore | None = None,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    app = FastAPI(title="ERP Analyst Agent API")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    app.state.graph = graph if graph is not None else _default_graph()
    app.state.tenant_resolver = tenant_resolver or _default_tenant_resolver
    app.state.tenant_lister = tenant_lister or _default_tenant_lister
    app.state.trace_store = trace_store or PostgresTraceStore(settings.database_url)
    app.state.rate_limiter = rate_limiter or RateLimiter()

    def _client_ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def _check_rate_limit(request: Request) -> None:
        decision = app.state.rate_limiter.check(_client_ip(request), time.time())
        if not decision.allowed:
            raise HTTPException(status_code=429, detail=decision.reason)

    def _resolve_tenant_or_404(tenant_name: str) -> str:
        tenant_id = app.state.tenant_resolver(tenant_name)
        if tenant_id is None:
            raise HTTPException(status_code=404, detail=f"Unknown tenant: {tenant_name!r}")
        return tenant_id

    def _finish(
        request: Request,
        thread_id: str,
        question: str,
        tenant_id: str | None,
        started_at: float,
        final_state: dict,
        node_timings: dict[str, float],
        interrupt_payload: dict | None,
    ) -> ChatResponse:
        duration_ms = (time.perf_counter() - started_at) * 1000
        trace_id = final_state.get("trace_id") or str(uuid.uuid4())

        # A crude per-character token estimate, since the fake-model unit
        # tests never produce real Anthropic usage metadata to count from
        # — see KNOWN_LIMITS.md. Still enough to exercise the rate
        # limiter's daily-ceiling behavior end to end.
        app.state.rate_limiter.record_request(_client_ip(request), time.time(), tokens_used=max(1, len(question) // 4))

        clarification_question = interrupt_payload.get("question") if interrupt_payload else None
        rows = None if interrupt_payload else final_state.get("rows")

        trace = Trace(
            trace_id=trace_id,
            tenant_id=tenant_id,
            question=question,
            sql=None if interrupt_payload else final_state.get("sql"),
            answer=None if interrupt_payload else final_state.get("answer"),
            confidence=None if interrupt_payload else final_state.get("confidence"),
            attempts=final_state.get("attempts", 0),
            model_tier=final_state.get("model_tier"),
            row_count=len(rows) if rows is not None else None,
            duration_ms=duration_ms,
            clarified=final_state.get("clarification_rounds", 0) > 0,
            node_timings=node_timings,
        )
        app.state.trace_store.save_trace(trace)

        return ChatResponse(
            trace_id=trace_id,
            thread_id=thread_id,
            answer=None if interrupt_payload else final_state.get("answer"),
            sql=None if interrupt_payload else final_state.get("sql"),
            rows=rows,
            confidence=None if interrupt_payload else final_state.get("confidence"),
            clarification_question=clarification_question,
        )

    @app.post("/chat", response_model=ChatResponse)
    def chat(body: ChatRequest, request: Request) -> ChatResponse:
        _check_rate_limit(request)
        tenant_id = _resolve_tenant_or_404(body.tenant_name)
        thread_id = body.thread_id or str(uuid.uuid4())
        trace_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        started_at = time.perf_counter()
        final_state, node_timings, interrupt_payload = run_with_timings(
            app.state.graph,
            {"question": body.question, "tenant_id": tenant_id, "model_tier": "cheap", "trace_id": trace_id},
            config=config,
        )
        return _finish(request, thread_id, body.question, tenant_id, started_at, final_state, node_timings, interrupt_payload)

    @app.post("/chat/resume", response_model=ChatResponse)
    def resume(body: ResumeRequest, request: Request) -> ChatResponse:
        _check_rate_limit(request)
        config = {"configurable": {"thread_id": body.thread_id}}

        started_at = time.perf_counter()
        final_state, node_timings, interrupt_payload = run_with_timings(app.state.graph, Command(resume=body.answer), config=config)
        return _finish(
            request,
            body.thread_id,
            final_state.get("question", ""),
            final_state.get("tenant_id"),
            started_at,
            final_state,
            node_timings,
            interrupt_payload,
        )

    @app.post("/feedback", status_code=204)
    def feedback(body: FeedbackRequest) -> None:
        app.state.trace_store.save_feedback(body.trace_id, body.vote)

    @app.get("/traces/{trace_id}")
    def get_trace_endpoint(trace_id: str) -> dict:
        trace = app.state.trace_store.get_trace(trace_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="trace not found")
        return trace

    @app.get("/tenants")
    def list_tenants() -> list[str]:
        return app.state.tenant_lister()

    return app
