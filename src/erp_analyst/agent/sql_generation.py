"""The model-calling boundary, kept as a single small, injectable
function so the graph's CONTROL FLOW (generate -> validate -> repair ->
execute -> answer) can be tested against the real LangGraph engine without
spending API calls — tests supply a fake SqlGenerator with canned
responses; src/erp_analyst/agent/models.py supplies the real one.

Prompt CONSTRUCTION (build_system_prompt/build_user_message) is kept
separate from the actual model call (real_sql_generator) specifically so
it can be unit-tested without an API key — only the final `model.invoke`
line needs real credentials.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from erp_analyst.agent.models import get_model
from erp_analyst.agent.schema_context import SCHEMA_CONTEXT
from erp_analyst.semantic.loader import SemanticLayer


@dataclass
class GeneratedSql:
    plan: str
    sql: str
    # Set instead of (plan, sql) when the question is genuinely ambiguous
    # in a way that changes which SQL to write — e.g. "revenue" could mean
    # invoiced or collected, "last quarter" could be calendar or fiscal.
    # When set, the graph pauses via interrupt() rather than generating
    # SQL against a guess. See graph.py's clarify_node.
    clarifying_question: str | None = None


class SqlGenerator(Protocol):
    def __call__(
        self, question: str, prior_errors: list[str] | None, prior_sql: str | None, tier: str
    ) -> GeneratedSql: ...


# (question, sql) pairs for a given incoming question — what a retriever
# (e.g. db.verified_queries.retrieve_similar, adapted) returns. Kept as a
# plain callable type here rather than importing db.verified_queries
# directly, so this module has no hard dependency on psycopg/the database
# just to define its config shape.
RetrieverFn = Callable[[str], list[tuple[str, str]]]


@dataclass
class GeneratorConfig:
    """Toggles used by the A-E ablation comparison (see
    scripts/ablation_eval.py) — each config switches one of these on top
    of the last, in order, to measure that single addition's contribution.
    Defaults are all-on except verified queries, which additionally needs
    a `retriever` passed to make_sql_generator (see below) — the best
    configuration is semantic layer + verified queries both on."""

    use_semantic_layer: bool = True
    use_verified_queries: bool = False


_SQL_BLOCK_RE = re.compile(r"```sql\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_sql(text: str) -> str:
    match = _SQL_BLOCK_RE.search(text)
    return (match.group(1) if match else text).strip().rstrip(";").strip()


def build_system_prompt(
    config: GeneratorConfig,
    semantic_layer: SemanticLayer | None = None,
    verified_examples: list[tuple[str, str]] | None = None,
) -> str:
    parts = [SCHEMA_CONTEXT]
    if config.use_semantic_layer:
        layer = semantic_layer or SemanticLayer.load()
        parts.append(layer.render())
    if config.use_verified_queries and verified_examples:
        parts.append("Similar previously-verified questions and their correct SQL (adapt, don't copy blindly):")
        for q, sql in verified_examples:
            parts.append(f"Q: {q}\n```sql\n{sql}\n```")
    return "\n\n".join(parts)


CLARIFY_PREFIX = "CLARIFY:"


def build_user_message(question: str, prior_errors: list[str] | None, prior_sql: str | None, allow_clarify: bool = True) -> str:
    clarify_instruction = (
        f"\n\nIf the question is genuinely ambiguous in a way that would change which SQL you write "
        f"(not just a detail you could reasonably assume), reply with exactly one line starting with "
        f'"{CLARIFY_PREFIX}" followed by your question, and nothing else — no plan, no SQL.'
        if allow_clarify
        else ""
    )
    if prior_errors:
        return (
            f"Question: {question}\n\n"
            f"Your previous SQL:\n```sql\n{prior_sql}\n```\n\n"
            "It was rejected for:\n" + "\n".join(f"- {e}" for e in prior_errors) + "\n\n"
            "Write a corrected query. Reply with a one-line plan, then the SQL in a ```sql fenced block."
        )
    return (
        f"Question: {question}\n\n"
        "Reply with a one-line plan (which tables/joins you'll use and why), "
        "then the SQL in a ```sql fenced block. SELECT only." + clarify_instruction
    )


def _parse_response(text: str) -> GeneratedSql:
    stripped = text.strip()
    if stripped.startswith(CLARIFY_PREFIX):
        return GeneratedSql(plan="", sql="", clarifying_question=stripped[len(CLARIFY_PREFIX) :].strip())
    sql = _extract_sql(text)
    plan = text.split("```")[0].strip()
    return GeneratedSql(plan=plan, sql=sql)


def make_sql_generator(
    config: GeneratorConfig | None = None,
    semantic_layer: SemanticLayer | None = None,
    retriever: RetrieverFn | None = None,
) -> SqlGenerator:
    """Builds a real, API-calling SqlGenerator closed over a specific
    ablation config — this is what lets the A-E comparison swap
    capabilities in and out without duplicating the prompt-assembly logic.

    `retriever`, when given, is called with the actual question on every
    generate/repair call (never at generator-construction time) — the
    relevant verified examples depend on THIS question, not a fixed set
    picked once up front.
    """
    cfg = config or GeneratorConfig()

    def generator(question: str, prior_errors: list[str] | None, prior_sql: str | None, tier: str) -> GeneratedSql:
        verified_examples = retriever(question) if (cfg.use_verified_queries and retriever) else None
        system_prompt = build_system_prompt(cfg, semantic_layer, verified_examples)
        model = get_model(tier)
        # Only offer the clarify option on a FRESH attempt (no prior_errors)
        # — once we have a concrete, invalid SQL attempt to fix, the model
        # should fix it, not relitigate whether the question was ambiguous.
        user_msg = build_user_message(question, prior_errors, prior_sql, allow_clarify=prior_errors is None)
        response = model.invoke([("system", system_prompt), ("user", user_msg)])
        text = response.content if isinstance(response.content, str) else str(response.content)
        return _parse_response(text)

    return generator


# The default real generator: all capabilities on, no verified-query
# examples pre-selected (a bare import of this module shouldn't need a
# database connection to look any up).
real_sql_generator: SqlGenerator = make_sql_generator()
