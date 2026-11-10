from erp_analyst.api.limits import RateLimiter, estimate_cost_usd


class TestEstimateCostUsd:
    def test_a_known_model_is_priced_from_the_table(self):
        cost = estimate_cost_usd("claude-haiku-5-5", input_tokens=1_000_000, output_tokens=0)
        assert cost == 1.0

    def test_output_tokens_use_the_output_rate(self):
        cost = estimate_cost_usd("claude-haiku-5-5", input_tokens=0, output_tokens=1_000_000)
        assert cost == 5.0

    def test_an_unknown_model_costs_zero_rather_than_raising(self):
        assert estimate_cost_usd("some-future-model", input_tokens=1000, output_tokens=1000) == 0.0


class TestRateLimiter:
    def test_requests_within_the_window_budget_are_allowed(self):
        limiter = RateLimiter(max_requests_per_window=3, window_seconds=60)
        now = 1000.0
        for _ in range(3):
            decision = limiter.check("1.2.3.4", now)
            assert decision.allowed is True
            limiter.record_request("1.2.3.4", now)

    def test_the_request_over_the_window_budget_is_denied(self):
        limiter = RateLimiter(max_requests_per_window=3, window_seconds=60)
        now = 1000.0
        for _ in range(3):
            limiter.record_request("1.2.3.4", now)

        decision = limiter.check("1.2.3.4", now)
        assert decision.allowed is False
        assert "rate limit" in decision.reason

    def test_requests_outside_the_window_do_not_count_against_the_budget(self):
        limiter = RateLimiter(max_requests_per_window=3, window_seconds=60)
        for _ in range(3):
            limiter.record_request("1.2.3.4", now=1000.0)

        decision = limiter.check("1.2.3.4", now=1000.0 + 61)
        assert decision.allowed is True

    def test_two_ips_have_independent_budgets(self):
        limiter = RateLimiter(max_requests_per_window=1, window_seconds=60)
        limiter.record_request("1.1.1.1", now=1000.0)

        assert limiter.check("1.1.1.1", now=1000.0).allowed is False
        assert limiter.check("2.2.2.2", now=1000.0).allowed is True

    def test_the_daily_token_ceiling_denies_further_requests_even_with_room_in_the_window(self):
        limiter = RateLimiter(max_requests_per_window=100, window_seconds=60, daily_token_ceiling=1000)
        limiter.record_request("1.2.3.4", now=1000.0, tokens_used=1000)

        decision = limiter.check("1.2.3.4", now=1000.0)
        assert decision.allowed is False
        assert "token ceiling" in decision.reason

    def test_the_token_ceiling_resets_on_a_new_day(self):
        limiter = RateLimiter(max_requests_per_window=100, window_seconds=60, daily_token_ceiling=1000)
        limiter.record_request("1.2.3.4", now=1000.0, tokens_used=1000)
        assert limiter.check("1.2.3.4", now=1000.0).allowed is False

        next_day = 1000.0 + 86400
        assert limiter.check("1.2.3.4", next_day).allowed is True
        assert limiter.tokens_used_today("1.2.3.4", next_day) == 0
