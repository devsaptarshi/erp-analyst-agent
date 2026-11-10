from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from erp_analyst.agent.graph import build_graph
from erp_analyst.agent.sql_generation import GeneratedSql
from erp_analyst.db.executor import ExecutionResult
from erp_analyst.tracing import run_with_timings


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


def test_happy_path_times_every_node_the_graph_actually_visited():
    generator = ScriptedGenerator([GeneratedSql(plan="plan", sql="SELECT name FROM suppliers")])
    executor_factory = executor_factory_for(ExecutionResult(ok=True, rows=[{"name": "Acme"}], columns=["name"]))
    graph = build_graph(sql_generator=generator, executor_factory=executor_factory)

    final_state, timings, interrupt_payload = run_with_timings(
        graph, {"question": "List suppliers", "tenant_id": "t1", "model_tier": "cheap"}
    )

    assert interrupt_payload is None
    assert final_state["rows"] == [{"name": "Acme"}]
    assert final_state["confidence"] == "high"
    assert set(timings) == {"generate_sql", "validate", "execute", "answer"}
    assert all(ms >= 0 for ms in timings.values())


def test_a_repair_round_trip_shows_up_as_extra_node_visits():
    generator = ScriptedGenerator(
        [
            GeneratedSql(plan="bad", sql="SELECT * FROM pg_shadow"),
            GeneratedSql(plan="fixed", sql="SELECT name FROM suppliers"),
        ]
    )
    executor_factory = executor_factory_for(ExecutionResult(ok=True, rows=[{"name": "Acme"}], columns=["name"]))
    graph = build_graph(sql_generator=generator, executor_factory=executor_factory)

    final_state, timings, _ = run_with_timings(graph, {"question": "x", "tenant_id": "t1", "model_tier": "cheap"})

    assert final_state["confidence"] == "medium"
    assert "repair" in timings


def test_an_interrupted_run_is_reported_with_the_clarifying_question_and_no_final_answer():
    generator = ScriptedGenerator([GeneratedSql(plan="", sql="", clarifying_question="Revenue or volume?")])
    executor_factory = executor_factory_for(ExecutionResult(ok=True, rows=[]))
    graph = build_graph(
        sql_generator=generator, executor_factory=executor_factory, checkpointer=InMemorySaver()
    )
    config = {"configurable": {"thread_id": "thread-1"}}

    final_state, _, interrupt_payload = run_with_timings(
        graph, {"question": "Who are our top customers?", "tenant_id": "t1", "model_tier": "cheap"}, config=config
    )

    assert interrupt_payload == {"question": "Revenue or volume?"}
    assert "answer" not in final_state


def test_resuming_after_an_interrupt_uses_a_command_and_still_times_the_remaining_nodes():
    generator = ScriptedGenerator(
        [
            GeneratedSql(plan="", sql="", clarifying_question="Revenue or volume?"),
            GeneratedSql(plan="plan", sql="SELECT name FROM customers"),
        ]
    )
    executor_factory = executor_factory_for(ExecutionResult(ok=True, rows=[{"name": "Acme"}], columns=["name"]))
    graph = build_graph(
        sql_generator=generator, executor_factory=executor_factory, checkpointer=InMemorySaver()
    )
    config = {"configurable": {"thread_id": "thread-2"}}

    run_with_timings(graph, {"question": "Who are our top customers?", "tenant_id": "t1", "model_tier": "cheap"}, config=config)
    final_state, timings, interrupt_payload = run_with_timings(graph, Command(resume="Revenue"), config=config)

    assert interrupt_payload is None
    assert final_state["rows"] == [{"name": "Acme"}]
    assert "generate_sql" in timings
