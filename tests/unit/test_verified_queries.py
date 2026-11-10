import pytest

from erp_analyst.db.verified_queries import add, init_table, retrieve_similar
from erp_analyst.semantic.embeddings import hashing_trick_embedder


@pytest.fixture
def clean_store(admin_conn):
    init_table(admin_conn)
    with admin_conn.cursor() as cur:
        cur.execute("DELETE FROM verified_queries")
    admin_conn.commit()
    yield admin_conn
    with admin_conn.cursor() as cur:
        cur.execute("DELETE FROM verified_queries")
    admin_conn.commit()


def test_retrieve_on_an_empty_store_returns_nothing(clean_store):
    results = retrieve_similar(clean_store, "how many suppliers", hashing_trick_embedder, k=3)
    assert results == []


def test_a_stored_question_is_retrievable_by_a_near_identical_question(clean_store):
    add(clean_store, "How many suppliers do we have?", "SELECT count(*) FROM suppliers", hashing_trick_embedder)
    results = retrieve_similar(clean_store, "How many suppliers are there?", hashing_trick_embedder, k=1)
    assert len(results) == 1
    assert results[0].sql == "SELECT count(*) FROM suppliers"


def test_retrieval_ranks_the_more_similar_question_first(clean_store):
    add(clean_store, "How many suppliers do we have?", "SELECT count(*) FROM suppliers", hashing_trick_embedder)
    add(clean_store, "What is our total revenue this quarter?", "SELECT sum(amount) FROM invoices", hashing_trick_embedder)

    results = retrieve_similar(clean_store, "How many suppliers are in the system?", hashing_trick_embedder, k=2)

    assert len(results) == 2
    assert results[0].sql == "SELECT count(*) FROM suppliers"  # closer match ranked first
    assert results[0].distance < results[1].distance


def test_k_limits_the_number_of_results(clean_store):
    for i in range(5):
        add(clean_store, f"question number {i} about suppliers", f"SELECT {i}", hashing_trick_embedder)
    results = retrieve_similar(clean_store, "a question about suppliers", hashing_trick_embedder, k=2)
    assert len(results) == 2


def test_tags_round_trip_correctly(clean_store):
    add(clean_store, "q", "SELECT 1", hashing_trick_embedder, tags=["yield", "multi-hop-join"])
    results = retrieve_similar(clean_store, "q", hashing_trick_embedder, k=1)
    assert set(results[0].tags) == {"yield", "multi-hop-join"}


def test_a_query_with_no_tags_defaults_to_an_empty_list(clean_store):
    add(clean_store, "q", "SELECT 1", hashing_trick_embedder)
    results = retrieve_similar(clean_store, "q", hashing_trick_embedder, k=1)
    assert results[0].tags == []
