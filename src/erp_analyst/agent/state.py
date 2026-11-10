from typing import TypedDict


class AgentState(TypedDict, total=False):
    question: str
    tenant_id: str  # set ONLY by the server from a verified session, never by the model — see graph.py
    context: str  # schema/semantic context assembled for this question
    plan: str
    sql: str
    validation_errors: list[str]
    rows: list[dict] | None
    attempts: int
    model_tier: str  # "cheap" | "strong"
    answer: str
    trace_id: str
