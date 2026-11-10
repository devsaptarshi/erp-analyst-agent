"""Exercises the REAL FastAPI app and REAL compiled LangGraph graph (via
TestClient -> create_app()), with a fake SqlGenerator, a fake executor and
an in-memory tenant resolver/trace store standing in for Postgres — same
"fake only the model and the DB" pattern as tests/unit/test_agent_graph.py.
"""
from __future__ import annotations

from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from erp_analyst.agent.graph import ResultCheck, build_graph
from erp_analyst.agent.sql_generation import GeneratedSql
from erp_analyst.api.app import create_app
from erp_analyst.api.limits import RateLimiter
from erp_analyst.db.executor import ExecutionResult
from erp_analyst.db.traces import Trace, TraceStore

TENANTS = {"Acme Leather Co": "11111111-1111-1111-1111-111111111111"}


class ScriptedGenerator:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, question, prior_errors, prior_sql, tier):
        self.calls.append((question, prior_errors, prior_sql, tier))
        return self.responses[len(self.calls) - 1]


def executor_factory_for(result: ExecutionResult):
    def factory(tenant_id: str):
        class _Executor:
            def execute(self, raw_sql: str) -> ExecutionResult:
                return result

        return _Executor()

    return factory


class InMemoryTraceStore(TraceStore):
    def __init__(self):
        self.traces: dict[str, Trace] = {}
        self.feedback: list[tuple[str, str]] = []

    def save_trace(self, trace: Trace) -> None:
        self.traces[trace.trace_id] = trace

    def get_trace(self, trace_id: str):
        trace = self.traces.get(trace_id)
        return asdict(trace) if trace else None

    def save_feedback(self, trace_id: str, vote: str) -> None:
        if vote not in ("up", "down"):
            raise ValueError(f"vote must be 'up' or 'down', got {vote!r}")
        self.feedback.append((trace_id, vote))


def make_client(graph, trace_store=None, rate_limiter=None):
    app = create_app(
        graph=graph,
        tenant_resolver=lambda name: TENANTS.get(name),
        tenant_lister=lambda: sorted(TENANTS),
        trace_store=trace_store or InMemoryTraceStore(),
        rate_limiter=rate_limiter or RateLimiter(),
    )
    return TestClient(app), app


def test_get_tenants_lists_the_configured_tenants():
    graph = build_graph(sql_generator=ScriptedGenerator([]), executor_factory=executor_factory_for(ExecutionResult(ok=True, rows=[])))
    client, _ = make_client(graph)

    response = client.get("/tenants")

    assert response.status_code == 200
    assert response.json() == ["Acme Leather Co"]


def test_chat_with_an_unknown_tenant_returns_404():
    graph = build_graph(sql_generator=ScriptedGenerator([]), executor_factory=executor_factory_for(ExecutionResult(ok=True, rows=[])))
    client, _ = make_client(graph)

    response = client.post("/chat", json={"question": "x", "tenant_name": "Nope Inc"})

    assert response.status_code == 404


def test_chat_happy_path_returns_answer_sql_rows_and_confidence_and_saves_a_trace():
    generator = ScriptedGenerator([GeneratedSql(plan="plan", sql="SELECT name FROM suppliers")])
    executor_factory = executor_factory_for(ExecutionResult(ok=True, rows=[{"name": "Acme"}], columns=["name"]))
    graph = build_graph(sql_generator=generator, executor_factory=executor_factory)
    trace_store = InMemoryTraceStore()
    client, _ = make_client(graph, trace_store=trace_store)

    response = client.post("/chat", json={"question": "List suppliers", "tenant_name": "Acme Leather Co"})

    assert response.status_code == 200
    body = response.json()
    assert body["rows"] == [{"name": "Acme"}]
    assert body["confidence"] == "high"
    assert body["clarification_question"] is None
    assert body["sql"] == "SELECT name FROM suppliers LIMIT 1000"  # the validator's LIMIT wrap, see sql_validator.py

    saved = trace_store.get_trace(body["trace_id"])
    assert saved is not None
    assert saved["tenant_id"] == TENANTS["Acme Leather Co"]
    assert saved["row_count"] == 1


def test_chat_pauses_for_clarification_and_resume_continues_the_same_thread():
    generator = ScriptedGenerator(
        [
            GeneratedSql(plan="", sql="", clarifying_question="Revenue or volume?"),
            GeneratedSql(plan="plan", sql="SELECT name FROM customers"),
        ]
    )
    executor_factory = executor_factory_for(ExecutionResult(ok=True, rows=[{"name": "Acme"}], columns=["name"]))
    graph = build_graph(sql_generator=generator, executor_factory=executor_factory, checkpointer=InMemorySaver())
    client, _ = make_client(graph)

    first = client.post("/chat", json={"question": "Who are our top customers?", "tenant_name": "Acme Leather Co"})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["clarification_question"] == "Revenue or volume?"
    assert first_body["answer"] is None
    thread_id = first_body["thread_id"]

    second = client.post("/chat/resume", json={"thread_id": thread_id, "answer": "Revenue"})
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["rows"] == [{"name": "Acme"}]
    assert second_body["clarification_question"] is None
    assert second_body["thread_id"] == thread_id


def test_feedback_is_recorded_against_a_trace():
    generator = ScriptedGenerator([GeneratedSql(plan="plan", sql="SELECT name FROM suppliers")])
    executor_factory = executor_factory_for(ExecutionResult(ok=True, rows=[{"name": "Acme"}], columns=["name"]))
    graph = build_graph(sql_generator=generator, executor_factory=executor_factory)
    trace_store = InMemoryTraceStore()
    client, _ = make_client(graph, trace_store=trace_store)

    chat_response = client.post("/chat", json={"question": "List suppliers", "tenant_name": "Acme Leather Co"})
    trace_id = chat_response.json()["trace_id"]

    feedback_response = client.post("/feedback", json={"trace_id": trace_id, "vote": "up"})

    assert feedback_response.status_code == 204
    assert trace_store.feedback == [(trace_id, "up")]


def test_feedback_rejects_an_invalid_vote():
    graph = build_graph(sql_generator=ScriptedGenerator([]), executor_factory=executor_factory_for(ExecutionResult(ok=True, rows=[])))
    client, _ = make_client(graph)

    response = client.post("/feedback", json={"trace_id": "t1", "vote": "sideways"})

    assert response.status_code == 422  # pydantic Literal rejects it before the handler runs


def test_get_trace_404s_for_an_unknown_trace_id():
    graph = build_graph(sql_generator=ScriptedGenerator([]), executor_factory=executor_factory_for(ExecutionResult(ok=True, rows=[])))
    client, _ = make_client(graph)

    response = client.get("/traces/does-not-exist")

    assert response.status_code == 404


def test_rate_limiting_returns_429_once_the_window_budget_is_exhausted():
    generator = ScriptedGenerator(
        [GeneratedSql(plan="plan", sql="SELECT name FROM suppliers") for _ in range(3)]
    )
    executor_factory = executor_factory_for(ExecutionResult(ok=True, rows=[{"name": "Acme"}], columns=["name"]))
    graph = build_graph(sql_generator=generator, executor_factory=executor_factory)
    limiter = RateLimiter(max_requests_per_window=2, window_seconds=60)
    client, _ = make_client(graph, rate_limiter=limiter)

    for _ in range(2):
        response = client.post("/chat", json={"question": "List suppliers", "tenant_name": "Acme Leather Co"})
        assert response.status_code == 200

    third = client.post("/chat", json={"question": "List suppliers", "tenant_name": "Acme Leather Co"})
    assert third.status_code == 429


def test_result_checker_objection_is_reflected_in_the_final_answer():
    generator = ScriptedGenerator(
        [
            GeneratedSql(plan="plan", sql="SELECT name FROM suppliers"),
            GeneratedSql(plan="fixed", sql="SELECT name FROM customers"),
        ]
    )
    executor_factory = executor_factory_for(ExecutionResult(ok=True, rows=[{"name": "Acme"}], columns=["name"]))
    checks = iter([ResultCheck(ok=False, concern="looks like the wrong table"), ResultCheck(ok=True)])
    graph = build_graph(
        sql_generator=generator,
        executor_factory=executor_factory,
        result_checker=lambda q, sql, rows: next(checks),
    )
    client, _ = make_client(graph)

    response = client.post("/chat", json={"question": "List suppliers", "tenant_name": "Acme Leather Co"})

    assert response.status_code == 200
    assert response.json()["confidence"] == "medium"


if __name__ == "__main__":
    pytest.main([__file__])
