"""A shared (NOT tenant-scoped) store of known-good (question, SQL) pairs,
retrieved by embedding similarity and injected as few-shot examples into
the SQL-generation prompt (see sql_generation.GeneratorConfig.verified_examples).

Deliberately not RLS-scoped: these rows are knowledge about how to query
the SCHEMA correctly (e.g. the nearest-earlier-goods-receipt join pattern
for tracing a batch's supplier), not tenant business data — every tenant
benefits from the same examples. Lives in its own table, written by an
admin-level process (scripts/seed_verified_queries.py), read by the
application through a connection that is NOT analyst_ro — see init below.
"""
from __future__ import annotations

from dataclasses import dataclass

import psycopg

from erp_analyst.semantic.embeddings import EMBEDDING_DIM, EmbedFn

CREATE_TABLE_SQL = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS verified_queries (
    id          serial PRIMARY KEY,
    question    text NOT NULL,
    sql         text NOT NULL,
    tags        text[] NOT NULL DEFAULT '{{}}',
    embedding   vector({EMBEDDING_DIM}) NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_verified_queries_embedding
    ON verified_queries USING hnsw (embedding vector_cosine_ops);
"""


def init_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
    conn.commit()


def add(conn: psycopg.Connection, question: str, sql: str, embed_fn: EmbedFn, tags: list[str] | None = None) -> None:
    embedding = embed_fn(question)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO verified_queries (question, sql, tags, embedding) VALUES (%s, %s, %s, %s)",
            (question, sql, tags or [], str(embedding)),
        )
    conn.commit()


@dataclass
class RetrievedExample:
    question: str
    sql: str
    tags: list[str]
    distance: float  # cosine distance — 0 = identical direction, 2 = opposite


def retrieve_similar(conn: psycopg.Connection, question: str, embed_fn: EmbedFn, k: int = 3) -> list[RetrievedExample]:
    embedding = embed_fn(question)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT question, sql, tags, embedding <=> %s AS distance "
            "FROM verified_queries ORDER BY distance ASC LIMIT %s",
            (str(embedding), k),
        )
        rows = cur.fetchall()
    return [RetrievedExample(question=q, sql=s, tags=list(t), distance=float(d)) for q, s, t, d in rows]
