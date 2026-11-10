import pytest

from erp_analyst.eval.mcnemar import mcnemar_test


def test_identical_configs_have_no_discordant_pairs_and_are_not_significant():
    a = [True, False, True, True, False]
    b = [True, False, True, True, False]
    result = mcnemar_test(a, b)
    assert result.n_a_only == 0
    assert result.n_b_only == 0
    assert result.p_value == 1.0
    assert not result.significant_at_05


def test_equal_numbers_of_each_discordant_direction_is_not_significant():
    # A beats B on 2 questions, B beats A on 2 questions — perfectly balanced disagreement.
    a_correct = [True, True, False, False, True, True]
    b_correct = [False, False, True, True, True, True]
    result = mcnemar_test(a_correct, b_correct)
    assert result.n_a_only == 2
    assert result.n_b_only == 2
    assert result.p_value == 1.0


def test_exact_binomial_matches_a_hand_computable_case():
    # n=5 discordant pairs, all favoring A (classic sign-test case):
    # exact two-sided p = 2 * C(5,0) * 0.5^5 = 2/32 = 0.0625.
    a_correct = [True] * 5 + [True] * 5  # 5 where A right B wrong, 5 where both right (concordant, ignored)
    b_correct = [False] * 5 + [True] * 5
    result = mcnemar_test(a_correct, b_correct)
    assert result.n_a_only == 5
    assert result.n_b_only == 0
    assert result.method == "exact_binomial"
    assert result.p_value == pytest.approx(0.0625, abs=1e-9)


def test_a_clear_large_imbalance_with_many_discordant_pairs_is_significant():
    # Reproduces the shape of the classic McNemar worked example (b=121, c=59):
    # a strong, clearly non-random imbalance should come out significant.
    a_correct = [True] * 121 + [False] * 59 + [True] * 50 + [False] * 50
    b_correct = [False] * 121 + [True] * 59 + [True] * 50 + [False] * 50
    result = mcnemar_test(a_correct, b_correct)
    assert result.n_a_only == 121
    assert result.n_b_only == 59
    assert result.method == "chi_square_continuity_corrected"
    assert result.p_value < 0.001
    assert result.significant_at_05


def test_a_small_imbalance_is_not_significant():
    a_correct = [True, False, True]
    b_correct = [False, True, True]  # b=1 (A only), c=1 (B only)
    result = mcnemar_test(a_correct, b_correct)
    assert not result.significant_at_05


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError, match="same length"):
        mcnemar_test([True, False], [True])


def test_empty_input_raises():
    with pytest.raises(ValueError, match="empty"):
        mcnemar_test([], [])


def test_p_value_is_always_between_0_and_1():
    import random

    random.seed(7)
    for _ in range(20):
        n = random.randint(1, 60)
        a = [random.random() < 0.6 for _ in range(n)]
        b = [random.random() < 0.6 for _ in range(n)]
        result = mcnemar_test(a, b)
        assert 0.0 <= result.p_value <= 1.0
