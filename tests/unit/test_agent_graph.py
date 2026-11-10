"""Exercises the REAL LangGraph engine (compiled graph, real routing),
with a fake SqlGenerator and a fake executor — the model and the database
are the only things faked; the control flow (generate -> validate ->
repair -> execute -> answer) is exactly what the real graph does.
"""
from erp_analyst.agent.graph import build_graph
from erp_analyst.agent.sql_generation import GeneratedSql
from erp_analyst.db.executor import ExecutionResult


class ScriptedGenerator:
    """Returns one scripted (plan, sql) pair per call, in order."""

    def __init__(self, responses: list[tuple[str, str]]):
        self.responses = responses
        self.calls: list[tuple[str, list[str] | None, str | None, str]] = []

    def __call__(self, question, prior_errors, prior_sql, tier) -> GeneratedSql:
        self.calls.append((question, prior_errors, prior_sql, tier))
        plan, sql = self.responses[len(self.calls) - 1]
        return GeneratedSql(plan=plan, sql=sql)


class ScriptedExecutor:
    def __init__(self, tenant_id: str, result: ExecutionResult):
        self.tenant_id = tenant_id
        self._result = result

    def execute(self, raw_sql: str) -> ExecutionResult:
        return self._result


def executor_factory_for(result: ExecutionResult):
    calls = []

    def factory(tenant_id: str):
        calls.append(tenant_id)
        return ScriptedExecutor(tenant_id, result)

    factory.calls = calls
    return factory


def test_happy_path_valid_sql_first_try_executes_and_answers():
    generator = ScriptedGenerator([("look up suppliers", "SELECT name FROM suppliers")])
    executor_factory = executor_factory_for(ExecutionResult(ok=True, rows=[{"name": "Acme"}], columns=["name"]))
    graph = build_graph(sql_generator=generator, executor_factory=executor_factory)

    result = graph.invoke({"question": "List suppliers", "tenant_id": "t1", "model_tier": "cheap"})

    assert result["rows"] == [{"name": "Acme"}]
    assert "1 row" in result["answer"]
    assert len(generator.calls) == 1  # no repair needed
    assert executor_factory.calls == ["t1"]  # tenant_id passed through correctly


def test_invalid_sql_triggers_repair_which_then_succeeds():
    generator = ScriptedGenerator(
        [
            ("bad plan", "SELECT * FROM pg_shadow"),  # rejected: not on allowlist
            ("fixed plan", "SELECT name FROM suppliers"),  # valid
        ]
    )
    executor_factory = executor_factory_for(ExecutionResult(ok=True, rows=[], columns=[]))
    graph = build_graph(sql_generator=generator, executor_factory=executor_factory)

    result = graph.invoke({"question": "List suppliers", "tenant_id": "t1", "model_tier": "cheap"})

    assert result["rows"] == []
    assert len(generator.calls) == 2
    # the repair call carries the validation errors from the first attempt
    _, prior_errors, prior_sql, _ = generator.calls[1]
    assert prior_errors and "pg_shadow" in prior_errors[0]
    assert prior_sql == "SELECT * FROM pg_shadow"


def test_repeated_invalid_sql_exhausts_the_repair_budget_and_never_executes():
    generator = ScriptedGenerator(
        [
            ("bad", "SELECT * FROM pg_shadow"),
            ("still bad", "DROP TABLE suppliers"),
            ("still bad again", "SELECT pg_sleep(5)"),
        ]
    )
    executor_factory = executor_factory_for(ExecutionResult(ok=True, rows=[{"should": "never run"}]))
    graph = build_graph(sql_generator=generator, executor_factory=executor_factory)

    result = graph.invoke({"question": "x", "tenant_id": "t1", "model_tier": "cheap"})

    assert result.get("rows") is None  # never executed (and "rows" is never even set, since execute_node never ran)
    assert executor_factory.calls == []  # the executor was never even called
    assert "couldn't produce a safe, valid query" in result["answer"]
    assert len(generator.calls) == 3  # initial + 2 repairs, budget respected exactly


def test_confidence_is_high_when_sql_is_valid_on_the_first_try():
    generator = ScriptedGenerator([("plan", "SELECT name FROM suppliers")])
    executor_factory = executor_factory_for(ExecutionResult(ok=True, rows=[{"name": "Acme"}], columns=["name"]))
    graph = build_graph(sql_generator=generator, executor_factory=executor_factory)

    result = graph.invoke({"question": "x", "tenant_id": "t1", "model_tier": "cheap"})

    assert result["confidence"] == "high"


def test_confidence_is_medium_when_a_repair_was_needed_to_succeed():
    generator = ScriptedGenerator(
        [
            ("bad plan", "SELECT * FROM pg_shadow"),
            ("fixed", "SELECT name FROM suppliers"),
        ]
    )
    executor_factory = executor_factory_for(ExecutionResult(ok=True, rows=[{"name": "Acme"}], columns=["name"]))
    graph = build_graph(sql_generator=generator, executor_factory=executor_factory)

    result = graph.invoke({"question": "x", "tenant_id": "t1", "model_tier": "cheap"})

    assert result["confidence"] == "medium"


def test_confidence_is_low_when_the_repair_budget_is_exhausted():
    generator = ScriptedGenerator(
        [
            ("bad", "SELECT * FROM pg_shadow"),
            ("still bad", "DROP TABLE suppliers"),
            ("still bad again", "SELECT pg_sleep(5)"),
        ]
    )
    executor_factory = executor_factory_for(ExecutionResult(ok=True, rows=[{"should": "never run"}]))
    graph = build_graph(sql_generator=generator, executor_factory=executor_factory)

    result = graph.invoke({"question": "x", "tenant_id": "t1", "model_tier": "cheap"})

    assert result["confidence"] == "low"


def test_a_database_execution_error_also_triggers_repair():
    generator = ScriptedGenerator(
        [
            ("plan", "SELECT name FROM suppliers"),  # passes validation
            ("retry", "SELECT name FROM customers"),  # also passes validation
        ]
    )
    results = iter([ExecutionResult(ok=False, error="Query failed: OperationalError"), ExecutionResult(ok=True, rows=[{"name": "x"}])])

    def factory(tenant_id: str):
        class _Exec:
            def execute(self, raw_sql: str) -> ExecutionResult:
                return next(results)

        return _Exec()

    graph = build_graph(sql_generator=generator, executor_factory=factory)
    result = graph.invoke({"question": "x", "tenant_id": "t1", "model_tier": "cheap"})

    assert result["rows"] == [{"name": "x"}]
    assert len(generator.calls) == 2


def test_the_model_tier_escalates_to_strong_on_the_second_repair_attempt():
    generator = ScriptedGenerator(
        [
            ("bad", "SELECT * FROM pg_shadow"),
            ("still bad", "DROP TABLE suppliers"),
            ("fixed", "SELECT name FROM suppliers"),
        ]
    )
    executor_factory = executor_factory_for(ExecutionResult(ok=True, rows=[]))
    graph = build_graph(sql_generator=generator, executor_factory=executor_factory)

    graph.invoke({"question": "x", "tenant_id": "t1", "model_tier": "cheap"})

    tiers_used = [call[3] for call in generator.calls]
    assert tiers_used == ["cheap", "cheap", "strong"]  # escalates only after the FIRST repair also fails


def test_tenant_id_is_passed_to_the_executor_unchanged_from_the_input_state():
    generator = ScriptedGenerator([("plan", "SELECT name FROM suppliers")])
    executor_factory = executor_factory_for(ExecutionResult(ok=True, rows=[]))
    graph = build_graph(sql_generator=generator, executor_factory=executor_factory)

    graph.invoke({"question": "x", "tenant_id": "a-specific-tenant-uuid", "model_tier": "cheap"})

    assert executor_factory.calls == ["a-specific-tenant-uuid"]
