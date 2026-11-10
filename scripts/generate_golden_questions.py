#!/usr/bin/env python3
"""Generates the 150-question golden eval set against the real seeded
database and writes it to tests/fixtures/golden_questions.json — every
answer-category ground truth was computed by actually executing SQL, not
hand-typed. Re-run this if scripts/seed_data.py's data ever changes.
"""
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from erp_analyst.config import settings
from erp_analyst.eval.golden_questions import generate_golden_questions, save

OUT_PATH = Path(__file__).resolve().parent.parent / "tests/fixtures/golden_questions.json"


def main() -> None:
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        questions = generate_golden_questions(conn)

    by_category: dict[str, int] = {}
    held_out = 0
    for q in questions:
        by_category[q.category] = by_category.get(q.category, 0) + 1
        if q.held_out:
            held_out += 1

    print(f"Generated {len(questions)} questions:")
    for cat, n in sorted(by_category.items()):
        print(f"  {cat}: {n}")
    print(f"  held_out: {held_out}")

    save(questions, OUT_PATH)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
