"""The model-calling boundary, kept as a single small, injectable
function so the graph's CONTROL FLOW (generate -> validate -> repair ->
execute -> answer) can be tested against the real LangGraph engine without
spending API calls — tests supply a fake SqlGenerator with canned
responses; src/erp_analyst/agent/models.py supplies the real one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from erp_analyst.agent.models import get_model
from erp_analyst.agent.schema_context import SCHEMA_CONTEXT


@dataclass
class GeneratedSql:
    plan: str
    sql: str


class SqlGenerator(Protocol):
    def __call__(
        self, question: str, prior_errors: list[str] | None, prior_sql: str | None, tier: str
    ) -> GeneratedSql: ...


_SQL_BLOCK_RE = re.compile(r"```sql\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_sql(text: str) -> str:
    match = _SQL_BLOCK_RE.search(text)
    return (match.group(1) if match else text).strip().rstrip(";").strip()


def real_sql_generator(question: str, prior_errors: list[str] | None, prior_sql: str | None, tier: str) -> GeneratedSql:
    model = get_model(tier)
    if prior_errors:
        user_msg = (
            f"Question: {question}\n\n"
            f"Your previous SQL:\n```sql\n{prior_sql}\n```\n\n"
            f"It was rejected for:\n" + "\n".join(f"- {e}" for e in prior_errors) + "\n\n"
            "Write a corrected query. Reply with a one-line plan, then the SQL in a ```sql fenced block."
        )
    else:
        user_msg = (
            f"Question: {question}\n\n"
            "Reply with a one-line plan (which tables/joins you'll use and why), "
            "then the SQL in a ```sql fenced block. SELECT only."
        )

    response = model.invoke([("system", SCHEMA_CONTEXT), ("user", user_msg)])
    text = response.content if isinstance(response.content, str) else str(response.content)
    sql = _extract_sql(text)
    plan = text.split("```")[0].strip()
    return GeneratedSql(plan=plan, sql=sql)
