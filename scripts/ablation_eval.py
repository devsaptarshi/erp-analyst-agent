#!/usr/bin/env python3
"""The A-E ablation comparison: runs the VISIBLE (non-held-out) golden
questions through 5 progressively-enhanced agent configurations and
compares each adjacent pair with McNemar's paired test, to measure what
each single addition actually contributes.

  A: schema only
  B: A + semantic layer
  C: B + verified-queries retrieval (pgvector, hashing-trick embedder)
  D: C + a result-check step
  E: D + cheap->strong model escalation on repair

Requires a real ANTHROPIC_API_KEY and a running, seeded Postgres instance
(docker compose up -d; scripts/init_db.py; scripts/seed_data.py;
scripts/seed_verified_queries.py). No key was available while building
this — see KNOWN_LIMITS.md. This script is complete and ready to run; it
has not yet produced real results.

Usage: ANTHROPIC_API_KEY=sk-... uv run python scripts/ablation_eval.py
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import itertools

from erp_analyst.agent.graph import build_graph
from erp_analyst.agent.result_check import make_result_checker
from erp_analyst.agent.sql_generation import GeneratorConfig, make_sql_generator
from erp_analyst.config import settings
from erp_analyst.db.executor import TenantScopedExecutor
from erp_analyst.db.verified_queries import retrieve_similar
from erp_analyst.eval.golden_questions import GoldenQuestion, load
from erp_analyst.eval.mcnemar import mcnemar_test
from erp_analyst.eval.scoring import score
from erp_analyst.semantic.embeddings import hashing_trick_embedder
from erp_analyst.semantic.loader import SemanticLayer

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "tests/fixtures/golden_questions.json"
RESULTS_PATH = Path(__file__).resolve().parent.parent / "results/ablation.json"


@dataclass
class AblationConfig:
    name: str
    generator_config: GeneratorConfig
    use_retriever: bool
    use_result_checker: bool
    allow_escalation: bool


CONFIGS = [
    AblationConfig("A_schema_only", GeneratorConfig(use_semantic_layer=False, use_verified_queries=False), False, False, False),
    AblationConfig("B_plus_semantic_layer", GeneratorConfig(use_semantic_layer=True, use_verified_queries=False), False, False, False),
    AblationConfig("C_plus_verified_queries", GeneratorConfig(use_semantic_layer=True, use_verified_queries=True), True, False, False),
    AblationConfig("D_plus_result_check", GeneratorConfig(use_semantic_layer=True, use_verified_queries=True), True, True, False),
    AblationConfig("E_plus_escalation", GeneratorConfig(use_semantic_layer=True, use_verified_queries=True), True, True, True),
]


def build_retriever(conn: psycopg.Connection):
    def retriever(question: str) -> list[tuple[str, str]]:
        examples = retrieve_similar(conn, question, hashing_trick_embedder, k=3)
        return [(e.question, e.sql) for e in examples]

    return retriever


def run_one_config(config: AblationConfig, questions: list[GoldenQuestion], admin_conn: psycopg.Connection) -> dict[str, bool]:
    semantic_layer = SemanticLayer.load()
    retriever = build_retriever(admin_conn) if config.use_retriever else None
    sql_generator = make_sql_generator(config.generator_config, semantic_layer=semantic_layer, retriever=retriever)
    result_checker = make_result_checker() if config.use_result_checker else None

    graph = build_graph(
        sql_generator=sql_generator,
        executor_factory=TenantScopedExecutor,
        allow_escalation=config.allow_escalation,
        result_checker=result_checker,
    )

    results: dict[str, bool] = {}
    for q in questions:
        if q.tenant_name is None:
            continue
        with admin_conn.cursor() as cur:
            cur.execute("SELECT id FROM tenants WHERE name = %s", (q.tenant_name,))
            row = cur.fetchone()
        if row is None:
            continue
        tenant_id = str(row[0])
        graph_result = graph.invoke({"question": q.question, "tenant_id": tenant_id, "model_tier": "cheap"})
        results[q.id] = score(q, graph_result)
    return results


def main() -> None:
    all_questions = load(FIXTURE_PATH)
    visible_questions = [q for q in all_questions if not q.held_out]
    print(f"Running {len(visible_questions)} visible questions through {len(CONFIGS)} configs...")

    with psycopg.connect(settings.database_url, autocommit=True) as admin_conn:
        per_config_results: dict[str, dict[str, bool]] = {}
        for config in CONFIGS:
            print(f"--- {config.name} ---")
            per_config_results[config.name] = run_one_config(config, visible_questions, admin_conn)
            n_correct = sum(per_config_results[config.name].values())
            print(f"{config.name}: {n_correct}/{len(visible_questions)} correct")

    comparisons = []
    for prev, cur in itertools.pairwise(CONFIGS):
        prev_results = per_config_results[prev.name]
        cur_results = per_config_results[cur.name]
        ids = [q.id for q in visible_questions if q.id in prev_results and q.id in cur_results]
        a_correct = [prev_results[i] for i in ids]
        b_correct = [cur_results[i] for i in ids]
        mcnemar_result = mcnemar_test(a_correct, b_correct)
        comparisons.append(
            {
                "from": prev.name,
                "to": cur.name,
                "n_prev_only_correct": mcnemar_result.n_a_only,
                "n_cur_only_correct": mcnemar_result.n_b_only,
                "p_value": mcnemar_result.p_value,
                "method": mcnemar_result.method,
                "significant_at_05": mcnemar_result.significant_at_05,
            }
        )
        print(f"{prev.name} -> {cur.name}: p={mcnemar_result.p_value:.4f} ({mcnemar_result.method})")

    RESULTS_PATH.parent.mkdir(exist_ok=True)
    RESULTS_PATH.write_text(
        json.dumps(
            {
                "n_visible_questions": len(visible_questions),
                "accuracy_by_config": {name: sum(r.values()) / len(r) for name, r in per_config_results.items()},
                "pairwise_mcnemar": comparisons,
            },
            indent=2,
        )
    )
    print(f"Wrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
