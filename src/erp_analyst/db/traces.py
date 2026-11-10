"""Per-run trace storage and feedback, backing the Week 3 "traces for each
run" + "thumbs up or down" product features. Lives in its own admin-written
table, same shape as verified_queries.py: not tenant business data (it's
question/SQL/timing metadata about how the agent answered), so no RLS
scoping, but never holds row-level *results* either — only a row count and
a short preview, never the full result set, since that WOULD be tenant data.

A real deployment with scale would swap this for Langfuse (see the build
spec's deployment table) rather than a hand-rolled table; this exists
because Langfuse needs its own hosted project/API key, which this
environment doesn't have — see KNOWN_LIMITS.md.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import psycopg

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id        text PRIMARY KEY,
    tenant_id       text,
    question        text NOT NULL,
    sql             text,
    answer          text,
    confidence      text,
    attempts        int NOT NULL DEFAULT 0,
    model_tier      text,
    row_count       int,
    duration_ms     double precision,
    clarified       boolean NOT NULL DEFAULT false,
    node_timings    jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS feedback (
    id          serial PRIMARY KEY,
    trace_id    text NOT NULL REFERENCES traces(trace_id),
    vote        text NOT NULL CHECK (vote IN ('up', 'down')),
    created_at  timestamptz NOT NULL DEFAULT now()
);
"""


def init_tables(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
    conn.commit()


@dataclass
class Trace:
    trace_id: str
    tenant_id: str | None
    question: str
    sql: str | None
    answer: str | None
    confidence: str | None
    attempts: int
    model_tier: str | None
    row_count: int | None
    duration_ms: float
    clarified: bool
    node_timings: dict[str, float]


def save_trace(conn: psycopg.Connection, trace: Trace) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO traces
                (trace_id, tenant_id, question, sql, answer, confidence,
                 attempts, model_tier, row_count, duration_ms, clarified, node_timings)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (trace_id) DO UPDATE SET
                sql = EXCLUDED.sql, answer = EXCLUDED.answer, confidence = EXCLUDED.confidence,
                attempts = EXCLUDED.attempts, model_tier = EXCLUDED.model_tier,
                row_count = EXCLUDED.row_count, duration_ms = EXCLUDED.duration_ms,
                clarified = EXCLUDED.clarified, node_timings = EXCLUDED.node_timings
            """,
            (
                trace.trace_id,
                trace.tenant_id,
                trace.question,
                trace.sql,
                trace.answer,
                trace.confidence,
                trace.attempts,
                trace.model_tier,
                trace.row_count,
                trace.duration_ms,
                trace.clarified,
                json.dumps(trace.node_timings),
            ),
        )
    conn.commit()


def get_trace(conn: psycopg.Connection, trace_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT trace_id, tenant_id, question, sql, answer, confidence,
                   attempts, model_tier, row_count, duration_ms, clarified, node_timings, created_at
            FROM traces WHERE trace_id = %s
            """,
            (trace_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    cols = [
        "trace_id", "tenant_id", "question", "sql", "answer", "confidence",
        "attempts", "model_tier", "row_count", "duration_ms", "clarified", "node_timings", "created_at",
    ]
    return dict(zip(cols, row, strict=True))


def save_feedback(conn: psycopg.Connection, trace_id: str, vote: str) -> None:
    if vote not in ("up", "down"):
        raise ValueError(f"vote must be 'up' or 'down', got {vote!r}")
    with conn.cursor() as cur:
        cur.execute("INSERT INTO feedback (trace_id, vote) VALUES (%s, %s)", (trace_id, vote))
    conn.commit()


class TraceStore:
    """Narrow interface the API depends on, so it can be swapped for a
    fake in tests instead of requiring a live Postgres instance."""

    def save_trace(self, trace: Trace) -> None:
        raise NotImplementedError

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def save_feedback(self, trace_id: str, vote: str) -> None:
        raise NotImplementedError


class PostgresTraceStore(TraceStore):
    def __init__(self, database_url: str):
        self.database_url = database_url

    def save_trace(self, trace: Trace) -> None:
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            save_trace(conn, trace)

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            return get_trace(conn, trace_id)

    def save_feedback(self, trace_id: str, vote: str) -> None:
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            save_feedback(conn, trace_id, vote)
