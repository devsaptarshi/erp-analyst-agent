"""Exercises the REAL LangGraph interrupt()/resume mechanism — a real
checkpointer (InMemorySaver for these unit tests; PostgresSaver is covered
separately against the real database), a real pause mid-graph, and a real
resume via Command(resume=...). Only the model is faked.
"""
import uuid

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from erp_analyst.agent.graph import build_graph
from erp_analyst.agent.sql_generation import GeneratedSql


def new_thread_config():
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


def executor_factory_ok(rows):
    def factory(tenant_id):
        class _Exec:
            def execute(self, raw_sql):
                from erp_analyst.db.executor import ExecutionResult

                return ExecutionResult(ok=True, rows=rows, columns=list(rows[0].keys()) if rows else [])

        return _Exec()

    return factory


def test_a_clarifying_question_pauses_the_graph_before_any_sql_is_generated():
    def generator(question, prior_errors, prior_sql, tier):
        return GeneratedSql(plan="", sql="", clarifying_question="Calendar quarter or fiscal quarter?")

    graph = build_graph(sql_generator=generator, executor_factory=executor_factory_ok([]), checkpointer=InMemorySaver())
    config = new_thread_config()

    result = graph.invoke({"question": "revenue last quarter", "tenant_id": "t1", "model_tier": "cheap"}, config=config)

    assert "__interrupt__" in result
    interrupts = result["__interrupt__"]
    assert len(interrupts) == 1
    assert interrupts[0].value["question"] == "Calendar quarter or fiscal quarter?"
    # Nothing was executed and no answer was produced — the graph is paused, not finished.
    assert result.get("rows") is None
    assert result.get("answer") is None


def test_resuming_after_clarification_continues_to_generate_sql_and_execute():
    calls = []

    def generator(question, prior_errors, prior_sql, tier):
        calls.append(question)
        if len(calls) == 1:
            return GeneratedSql(plan="", sql="", clarifying_question="Calendar quarter or fiscal quarter?")
        # Second call happens AFTER resume, with the clarified question.
        return GeneratedSql(plan="list suppliers", sql="SELECT name FROM suppliers")

    graph = build_graph(
        sql_generator=generator, executor_factory=executor_factory_ok([{"name": "Acme"}]), checkpointer=InMemorySaver()
    )
    config = new_thread_config()

    first = graph.invoke({"question": "revenue last quarter", "tenant_id": "t1", "model_tier": "cheap"}, config=config)
    assert "__interrupt__" in first

    resumed = graph.invoke(Command(resume="fiscal quarter"), config=config)

    assert resumed["rows"] == [{"name": "Acme"}]
    assert len(calls) == 2
    # The clarified question (with the Q&A folded in) was what generated the final SQL.
    assert "fiscal quarter" in calls[1]
    assert "revenue last quarter" in calls[1]  # the original question is preserved, not replaced


def test_clarification_is_capped_at_one_round_even_if_the_model_keeps_asking():
    def generator(question, prior_errors, prior_sql, tier):
        # Always asks for clarification, no matter what — simulates a
        # model that never settles. Must not loop forever.
        return GeneratedSql(plan="", sql="", clarifying_question="Still unclear, can you clarify?")

    graph = build_graph(sql_generator=generator, executor_factory=executor_factory_ok([]), checkpointer=InMemorySaver())
    config = new_thread_config()

    first = graph.invoke({"question": "x", "tenant_id": "t1", "model_tier": "cheap"}, config=config)
    assert "__interrupt__" in first

    # Resume once — the cap (MAX_CLARIFY_ROUNDS=1) means this must NOT
    # interrupt a second time, even though the generator asks again.
    resumed = graph.invoke(Command(resume="still not sure"), config=config)

    assert "__interrupt__" not in resumed
    # Falls through to validate with empty SQL (since the second
    # generate_sql call also returned a clarifying_question, which is
    # ignored past the round cap) -> fails validation -> eventually answers
    # with an honest failure message, never hangs and never guesses.
    assert resumed.get("answer") is not None


def test_a_question_with_no_ambiguity_never_interrupts_at_all():
    def generator(question, prior_errors, prior_sql, tier):
        return GeneratedSql(plan="plan", sql="SELECT name FROM suppliers")

    graph = build_graph(
        sql_generator=generator, executor_factory=executor_factory_ok([{"name": "Acme"}]), checkpointer=InMemorySaver()
    )
    result = graph.invoke({"question": "list suppliers", "tenant_id": "t1", "model_tier": "cheap"}, config=new_thread_config())

    assert "__interrupt__" not in result
    assert result["rows"] == [{"name": "Acme"}]
