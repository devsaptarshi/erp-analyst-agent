"""The agent's LangGraph state machine.

generate_sql -> validate -(ok)-> execute -> answer
                   |-(bad, attempts<2)-> repair -> validate (loop)
                   |-(bad, attempts>=2)-> answer (explains the failure)
execute -(db error)-> repair (same loop, same attempt budget) -> validate
execute -(ok)-> answer

Two real exits: a successful answer with rows, or an honest explanation
after the repair budget (2 attempts, per the build spec) is exhausted —
never a silent wrong answer and never a raw DB/stack-trace error surfaced
to the user. The build spec's own "seven steps, three exits" diagram was
never resolved to concrete node names (see the extracted spec notes) — this
is a from-scratch, reasonable design satisfying the same intent: plan,
generate, validate, execute, and a bounded repair loop, never looping
forever and never executing something that failed validation.
"""
from __future__ import annotations

from collections.abc import Callable

from langgraph.graph import END, StateGraph

from erp_analyst.agent.sql_generation import GeneratedSql, SqlGenerator, real_sql_generator
from erp_analyst.agent.state import AgentState
from erp_analyst.db.executor import ExecutionResult, TenantScopedExecutor
from erp_analyst.validation.sql_validator import validate

MAX_REPAIR_ATTEMPTS = 2

ExecutorFactory = Callable[[str], "ExecutorProtocol"]


class ExecutorProtocol:
    def execute(self, raw_sql: str) -> ExecutionResult: ...


def build_graph(
    sql_generator: SqlGenerator = real_sql_generator,
    executor_factory: ExecutorFactory = TenantScopedExecutor,
):
    def generate_sql_node(state: AgentState) -> dict:
        tier = state.get("model_tier", "cheap")
        generated: GeneratedSql = sql_generator(state["question"], None, None, tier)
        return {"plan": generated.plan, "sql": generated.sql, "attempts": 0}

    def validate_node(state: AgentState) -> dict:
        result = validate(state["sql"])
        if result.ok:
            return {"sql": result.sql, "validation_errors": []}
        return {"validation_errors": result.errors}

    def route_after_validate(state: AgentState) -> str:
        if not state.get("validation_errors"):
            return "execute"
        if state.get("attempts", 0) < MAX_REPAIR_ATTEMPTS:
            return "repair"
        return "answer"

    def repair_node(state: AgentState) -> dict:
        attempts = state.get("attempts", 0) + 1
        # Escalate to the strong model only once the cheap model has
        # already failed once — most questions never need this.
        tier = "strong" if attempts >= 2 else state.get("model_tier", "cheap")
        generated = sql_generator(state["question"], state.get("validation_errors"), state.get("sql"), tier)
        return {"plan": generated.plan, "sql": generated.sql, "attempts": attempts, "model_tier": tier}

    def execute_node(state: AgentState) -> dict:
        executor = executor_factory(state["tenant_id"])
        result = executor.execute(state["sql"])
        if result.ok:
            return {"rows": result.rows}
        return {"rows": None, "validation_errors": [result.error or "execution failed"]}

    def route_after_execute(state: AgentState) -> str:
        if state.get("rows") is not None:
            return "answer"
        if state.get("attempts", 0) < MAX_REPAIR_ATTEMPTS:
            return "repair"
        return "answer"

    def answer_node(state: AgentState) -> dict:
        if state.get("rows") is not None:
            rows = state["rows"]
            answer = f"Found {len(rows)} row(s)." if rows else "No matching rows were found."
        else:
            errors = state.get("validation_errors") or ["unknown error"]
            answer = (
                "I couldn't produce a safe, valid query for this question after "
                f"{MAX_REPAIR_ATTEMPTS} attempt(s). Last issue: " + "; ".join(errors)
            )
        return {"answer": answer}

    graph = StateGraph(AgentState)
    graph.add_node("generate_sql", generate_sql_node)
    graph.add_node("validate", validate_node)
    graph.add_node("repair", repair_node)
    graph.add_node("execute", execute_node)
    graph.add_node("answer", answer_node)

    graph.set_entry_point("generate_sql")
    graph.add_edge("generate_sql", "validate")
    graph.add_conditional_edges("validate", route_after_validate, {"execute": "execute", "repair": "repair", "answer": "answer"})
    graph.add_edge("repair", "validate")
    graph.add_conditional_edges("execute", route_after_execute, {"answer": "answer", "repair": "repair"})
    graph.add_edge("answer", END)

    return graph.compile()
