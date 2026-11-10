"""Same interrupt/resume mechanism as tests/unit/test_agent_clarify.py,
but against a REAL PostgresSaver on the real local Postgres instance —
proves a paused (interrupted) run's state actually persists outside the
process, which is the whole point of using PostgresSaver over the
in-memory one: a real deployment's web server can restart between a
question being asked and a human answering the clarification.
"""
import uuid

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command

from erp_analyst.agent.graph import build_graph
from erp_analyst.agent.sql_generation import GeneratedSql
from erp_analyst.config import settings
from erp_analyst.db.executor import ExecutionResult


def executor_factory_ok(rows):
    def factory(tenant_id):
        class _Exec:
            def execute(self, raw_sql):
                return ExecutionResult(ok=True, rows=rows, columns=list(rows[0].keys()) if rows else [])

        return _Exec()

    return factory


def test_an_interrupted_run_survives_being_reloaded_from_a_fresh_postgressaver_instance():
    """Simulates a process restart: the graph that PAUSES is a different
    Python object (a fresh PostgresSaver connection) than the one that
    RESUMES — only the shared Postgres-backed thread_id ties them
    together, exactly as it would across two separate web requests hitting
    two different server processes/connections."""
    calls = []

    def generator(question, prior_errors, prior_sql, tier):
        calls.append(question)
        if len(calls) == 1:
            return GeneratedSql(plan="", sql="", clarifying_question="Calendar quarter or fiscal quarter?")
        return GeneratedSql(plan="list suppliers", sql="SELECT name FROM suppliers")

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    with PostgresSaver.from_conn_string(settings.database_url) as checkpointer_a:
        checkpointer_a.setup()
        graph_a = build_graph(
            sql_generator=generator, executor_factory=executor_factory_ok([{"name": "Acme"}]), checkpointer=checkpointer_a
        )
        paused = graph_a.invoke({"question": "revenue last quarter", "tenant_id": "t1", "model_tier": "cheap"}, config=config)
        assert "__interrupt__" in paused
        assert paused["__interrupt__"][0].value["question"] == "Calendar quarter or fiscal quarter?"

    # Fresh connection, fresh graph object — nothing in Python memory
    # carries over except the thread_id and the shared Postgres state.
    with PostgresSaver.from_conn_string(settings.database_url) as checkpointer_b:
        graph_b = build_graph(
            sql_generator=generator, executor_factory=executor_factory_ok([{"name": "Acme"}]), checkpointer=checkpointer_b
        )
        resumed = graph_b.invoke(Command(resume="fiscal quarter"), config=config)

    assert resumed["rows"] == [{"name": "Acme"}]
    assert len(calls) == 2
    assert "fiscal quarter" in calls[1]
