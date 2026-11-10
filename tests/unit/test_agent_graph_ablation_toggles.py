"""Tests the two toggles the A-E ablation comparison needs from the graph
itself: allow_escalation (config E) and result_checker (config D) —
against the real compiled LangGraph engine, fakes only the model and the
DB executor, same pattern as test_agent_graph.py.
"""
from erp_analyst.agent.graph import ResultCheck, build_graph
from erp_analyst.agent.sql_generation import GeneratedSql
from erp_analyst.db.executor import ExecutionResult


class ScriptedGenerator:
    def __init__(self, responses: list[tuple[str, str]]):
        self.responses = responses
        self.calls: list[tuple[str, list[str] | None, str | None, str]] = []

    def __call__(self, question, prior_errors, prior_sql, tier) -> GeneratedSql:
        self.calls.append((question, prior_errors, prior_sql, tier))
        plan, sql = self.responses[len(self.calls) - 1]
        return GeneratedSql(plan=plan, sql=sql)


def always_invalid_executor_factory():
    def factory(tenant_id):
        class _Exec:
            def execute(self, raw_sql):
                return ExecutionResult(ok=True, rows=[], columns=[])

        return _Exec()

    return factory


def test_escalation_disabled_keeps_the_tier_fixed_through_both_repair_attempts():
    generator = ScriptedGenerator(
        [
            ("bad", "SELECT * FROM pg_shadow"),
            ("still bad", "DROP TABLE suppliers"),
            ("fixed", "SELECT name FROM suppliers"),
        ]
    )
    graph = build_graph(sql_generator=generator, executor_factory=always_invalid_executor_factory(), allow_escalation=False)
    graph.invoke({"question": "x", "tenant_id": "t1", "model_tier": "cheap"})

    tiers_used = [call[3] for call in generator.calls]
    assert tiers_used == ["cheap", "cheap", "cheap"]  # never escalates, unlike the default (allow_escalation=True) behavior


def test_escalation_enabled_still_escalates_as_before_default_behavior():
    generator = ScriptedGenerator(
        [
            ("bad", "SELECT * FROM pg_shadow"),
            ("still bad", "DROP TABLE suppliers"),
            ("fixed", "SELECT name FROM suppliers"),
        ]
    )
    graph = build_graph(sql_generator=generator, executor_factory=always_invalid_executor_factory(), allow_escalation=True)
    graph.invoke({"question": "x", "tenant_id": "t1", "model_tier": "cheap"})

    tiers_used = [call[3] for call in generator.calls]
    assert tiers_used == ["cheap", "cheap", "strong"]


def test_no_result_checker_never_adds_the_result_check_step():
    generator = ScriptedGenerator([("plan", "SELECT name FROM suppliers")])

    def executor_factory(tenant_id):
        class _Exec:
            def execute(self, raw_sql):
                return ExecutionResult(ok=True, rows=[{"name": "Acme"}], columns=["name"])

        return _Exec()

    graph = build_graph(sql_generator=generator, executor_factory=executor_factory, result_checker=None)
    result = graph.invoke({"question": "x", "tenant_id": "t1", "model_tier": "cheap"})
    assert result["rows"] == [{"name": "Acme"}]


def test_a_result_checker_that_approves_lets_the_answer_through_unchanged():
    generator = ScriptedGenerator([("plan", "SELECT name FROM suppliers")])

    def executor_factory(tenant_id):
        class _Exec:
            def execute(self, raw_sql):
                return ExecutionResult(ok=True, rows=[{"name": "Acme"}], columns=["name"])

        return _Exec()

    def approving_checker(question, sql, rows):
        return ResultCheck(ok=True)

    graph = build_graph(sql_generator=generator, executor_factory=executor_factory, result_checker=approving_checker)
    result = graph.invoke({"question": "x", "tenant_id": "t1", "model_tier": "cheap"})
    assert result["rows"] == [{"name": "Acme"}]


def test_a_result_checker_that_objects_triggers_repair_and_the_repaired_result_is_used():
    generator = ScriptedGenerator(
        [
            ("plan", "SELECT name FROM suppliers"),  # execute succeeds, but the checker will object
            ("fixed plan", "SELECT name FROM customers"),  # repair attempt
        ]
    )
    results = iter([[{"name": "WrongTable"}], [{"name": "RightTable"}]])

    def executor_factory(tenant_id):
        class _Exec:
            def execute(self, raw_sql):
                return ExecutionResult(ok=True, rows=next(results), columns=["name"])

        return _Exec()

    call_count = {"n": 0}

    def strict_checker(question, sql, rows):
        call_count["n"] += 1
        if rows and rows[0]["name"] == "WrongTable":
            return ResultCheck(ok=False, concern="This looks like the wrong table was queried.")
        return ResultCheck(ok=True)

    graph = build_graph(sql_generator=generator, executor_factory=executor_factory, result_checker=strict_checker)
    result = graph.invoke({"question": "x", "tenant_id": "t1", "model_tier": "cheap"})

    assert result["rows"] == [{"name": "RightTable"}]
    assert call_count["n"] == 2  # checked both the rejected and the accepted result
    # the repair prompt saw the checker's concern, not a validator error
    assert "wrong table" in generator.calls[1][1][0].lower()


def test_a_result_checker_that_always_objects_still_respects_the_repair_budget():
    generator = ScriptedGenerator(
        [
            ("plan1", "SELECT name FROM suppliers"),
            ("plan2", "SELECT name FROM customers"),
            ("plan3", "SELECT name FROM products"),
        ]
    )

    def executor_factory(tenant_id):
        class _Exec:
            def execute(self, raw_sql):
                return ExecutionResult(ok=True, rows=[{"name": "x"}], columns=["name"])

        return _Exec()

    def always_objecting_checker(question, sql, rows):
        return ResultCheck(ok=False, concern="never satisfied")

    graph = build_graph(sql_generator=generator, executor_factory=executor_factory, result_checker=always_objecting_checker)
    result = graph.invoke({"question": "x", "tenant_id": "t1", "model_tier": "cheap"})

    assert result.get("rows") is None  # never accepted
    assert len(generator.calls) == 3  # initial + 2 repairs, same budget as validation failures
    assert "safe, valid query" in result["answer"] or "never satisfied" in result["answer"]
