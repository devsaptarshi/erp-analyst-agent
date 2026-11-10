"""The agent's LangGraph state machine.

generate_sql -(ambiguous, round 0)-> clarify -(interrupt, resume)-> generate_sql
             -(not ambiguous, or already clarified once)-> validate -(ok)-> execute -> answer
                   |-(bad, attempts<2)-> repair -> validate (loop)
                   |-(bad, attempts>=2)-> answer (explains the failure)
execute -(db error)-> repair (same loop, same attempt budget) -> validate
execute -(ok)-> answer

Three real exits now: a successful answer with rows, an honest
explanation after the repair budget (2 attempts, per the build spec) is
exhausted, or (new this week) the graph pausing mid-run via LangGraph's
native interrupt() to ask a genuinely ambiguous question back to a human
before ever generating SQL against a guess. Never a silent wrong answer
and never a raw DB/stack-trace error surfaced to the user. The build
spec's own "seven steps, three exits" diagram was never resolved to
concrete node names (see the extracted spec notes) — this is a from-
scratch, reasonable design satisfying the same intent.

Clarification is capped at one round (MAX_CLARIFY_ROUNDS): if the model is
still unsure after a human has already answered once, it proceeds to
generate SQL anyway rather than risking an infinite back-and-forth — a
bounded budget, same principle as the repair loop.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from erp_analyst.agent.sql_generation import GeneratedSql, SqlGenerator, real_sql_generator
from erp_analyst.agent.state import AgentState
from erp_analyst.db.executor import ExecutionResult, TenantScopedExecutor
from erp_analyst.validation.sql_validator import validate

MAX_REPAIR_ATTEMPTS = 2
MAX_CLARIFY_ROUNDS = 1

ExecutorFactory = Callable[[str], "ExecutorProtocol"]


class ExecutorProtocol:
    def execute(self, raw_sql: str) -> ExecutionResult: ...


@dataclass
class ResultCheck:
    ok: bool
    concern: str | None = None  # why the result looks wrong, fed back into the repair prompt like a validation error


# Reviews (question, sql, rows) after a successful execution, before
# answering — the "D" step in the A-E ablation comparison. Optional: most
# of the time the executed, validated SQL's result is trustworthy as-is;
# this exists to catch the cases where it technically ran but is probably
# not what was asked (e.g. an empty result for a question that obviously
# should have matched something).
ResultChecker = Callable[[str, str, "list[dict]"], ResultCheck]


def build_graph(
    sql_generator: SqlGenerator = real_sql_generator,
    executor_factory: ExecutorFactory = TenantScopedExecutor,
    checkpointer=None,
    allow_escalation: bool = True,
    result_checker: ResultChecker | None = None,
):
    def generate_sql_node(state: AgentState) -> dict:
        tier = state.get("model_tier", "cheap")
        generated: GeneratedSql = sql_generator(state["question"], None, None, tier)
        if generated.clarifying_question:
            # "sql"/"plan" are set even here (not left unset) so that if
            # route_after_generate forces a fallthrough to "validate"
            # anyway (the MAX_CLARIFY_ROUNDS cap hit, with the model still
            # asking for clarification), validate_node has a real,
            # if-empty, string to validate instead of a missing key —
            # found by a test that hit exactly this path.
            return {"plan": "", "sql": generated.sql, "attempts": 0, "clarification_question": generated.clarifying_question}
        return {"plan": generated.plan, "sql": generated.sql, "attempts": 0, "clarification_question": None}

    def route_after_generate(state: AgentState) -> str:
        if state.get("clarification_question") and state.get("clarification_rounds", 0) < MAX_CLARIFY_ROUNDS:
            return "clarify"
        return "validate"

    def clarify_node(state: AgentState) -> dict:
        # Pauses the graph here. The caller resumes with
        # graph.invoke(Command(resume=<the human's answer>), config=...)
        # using the SAME thread_id config as the original invoke — that's
        # what the checkpointer is for: without one, interrupt() has
        # nowhere to persist this paused state to.
        answer = interrupt({"question": state["clarification_question"]})
        combined_question = f"{state['question']}\n\n(Clarification asked: {state['clarification_question']}\nHuman answered: {answer})"
        return {
            "question": combined_question,
            "clarification_question": None,
            "clarification_rounds": state.get("clarification_rounds", 0) + 1,
        }

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
        # already failed once, and only when escalation is enabled at all
        # (the "E" step in the A-E ablation comparison — configs A-D keep
        # model_tier fixed, to measure whether escalation itself helps).
        current_tier = state.get("model_tier", "cheap")
        tier = "strong" if (allow_escalation and attempts >= 2) else current_tier
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
            return "result_check" if result_checker else "answer"
        if state.get("attempts", 0) < MAX_REPAIR_ATTEMPTS:
            return "repair"
        return "answer"

    def result_check_node(state: AgentState) -> dict:
        check = result_checker(state["question"], state["sql"], state["rows"])
        if check.ok:
            return {}
        # Treat a failed result-check like a validation failure: it
        # re-enters the SAME bounded repair loop and the SAME attempt
        # budget, never a separate unbounded one.
        return {"rows": None, "validation_errors": [check.concern or "result failed review"]}

    def route_after_result_check(state: AgentState) -> str:
        if state.get("rows") is not None:
            return "answer"
        if state.get("attempts", 0) < MAX_REPAIR_ATTEMPTS:
            return "repair"
        return "answer"

    def answer_node(state: AgentState) -> dict:
        if state.get("rows") is not None:
            rows = state["rows"]
            answer = f"Found {len(rows)} row(s)." if rows else "No matching rows were found."
            # "high" = valid SQL on the first try, nothing to repair or
            # second-guess. "medium" = it got there, but only after a
            # repair attempt and/or a result-check objection — the kind of
            # answer worth a quick human glance before trusting it blindly.
            confidence = "high" if state.get("attempts", 0) == 0 else "medium"
            return {"answer": answer, "confidence": confidence}
        errors = state.get("validation_errors") or ["unknown error"]
        answer = (
            "I couldn't produce a safe, valid query for this question after "
            f"{MAX_REPAIR_ATTEMPTS} attempt(s). Last issue: " + "; ".join(errors)
        )
        return {"answer": answer, "confidence": "low"}

    graph = StateGraph(AgentState)
    graph.add_node("generate_sql", generate_sql_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("validate", validate_node)
    graph.add_node("repair", repair_node)
    graph.add_node("execute", execute_node)
    graph.add_node("answer", answer_node)

    graph.set_entry_point("generate_sql")
    graph.add_conditional_edges("generate_sql", route_after_generate, {"clarify": "clarify", "validate": "validate"})
    graph.add_edge("clarify", "generate_sql")
    graph.add_conditional_edges("validate", route_after_validate, {"execute": "execute", "repair": "repair", "answer": "answer"})
    graph.add_edge("repair", "validate")

    if result_checker is not None:
        graph.add_node("result_check", result_check_node)
        graph.add_conditional_edges("execute", route_after_execute, {"result_check": "result_check", "repair": "repair"})
        graph.add_conditional_edges("result_check", route_after_result_check, {"answer": "answer", "repair": "repair"})
    else:
        graph.add_conditional_edges("execute", route_after_execute, {"answer": "answer", "repair": "repair"})

    graph.add_edge("answer", END)

    return graph.compile(checkpointer=checkpointer)
