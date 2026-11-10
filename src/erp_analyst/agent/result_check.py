"""The real, API-calling ResultChecker (config D/E's "result-check step"
in the A-E ablation) — reviews (question, sql, rows) and flags results
that executed successfully but look wrong. Same separation as
sql_generation.py: prompt construction is a pure function
(build_check_prompt), kept apart from the actual model call so it's
testable without an API key.
"""
from __future__ import annotations

from erp_analyst.agent.graph import ResultCheck
from erp_analyst.agent.models import get_model

CONCERN_PREFIX = "CONCERN:"


def build_check_prompt(question: str, sql: str, rows: list[dict]) -> str:
    preview = rows[:5]
    return (
        f"Question: {question}\n\n"
        f"SQL that was run:\n```sql\n{sql}\n```\n\n"
        f"Result ({len(rows)} row(s), first 5 shown): {preview}\n\n"
        "Does this result actually answer the question? Check especially for: "
        "an empty result where the question clearly expects data to exist, "
        "a result that answers a DIFFERENT question than the one asked, "
        "or an obviously wrong magnitude (e.g. a percentage over 100, a negative count). "
        f'If something looks wrong, reply with exactly one line starting with "{CONCERN_PREFIX}" '
        "followed by what's wrong. Otherwise reply with exactly: OK"
    )


def _parse_check_response(text: str) -> ResultCheck:
    stripped = text.strip()
    if stripped.startswith(CONCERN_PREFIX):
        return ResultCheck(ok=False, concern=stripped[len(CONCERN_PREFIX) :].strip())
    return ResultCheck(ok=True)


def make_result_checker(tier: str = "cheap"):
    def checker(question: str, sql: str, rows: list[dict]) -> ResultCheck:
        model = get_model(tier)
        response = model.invoke([("user", build_check_prompt(question, sql, rows))])
        text = response.content if isinstance(response.content, str) else str(response.content)
        return _parse_check_response(text)

    return checker


real_result_checker = make_result_checker()
