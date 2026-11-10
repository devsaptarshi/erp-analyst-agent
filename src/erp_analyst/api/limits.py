"""Per-IP rate limiting and token-cost tracking for the public demo (the
build spec's "Abuse limits" row: "Rate limit per IP, daily token ceiling,
read-only demo"). Pure in-memory bookkeeping, no DB — a restart resets
everyone's counters, which is fine for a read-only demo and avoids adding
a stateful dependency just for this. The caller supplies `now` explicitly
(rather than this module calling time.time() itself) so it's deterministic
to unit test.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

# Anthropic list pricing per 1M tokens, as of when this was written —
# check current pricing before trusting this for real cost reporting (see
# the build spec's own "check current pricing" note for the deploy host).
_PRICING_PER_MILLION_TOKENS: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (1.0, 5.0),  # (input, output) USD/1M tokens
    "claude-sonnet-5-5": (3.0, 15.0),
}


def estimate_cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> float:
    input_rate, output_rate = _PRICING_PER_MILLION_TOKENS.get(model_id, (0.0, 0.0))
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


@dataclass
class RateLimitDecision:
    allowed: bool
    reason: str | None = None


@dataclass
class _IpState:
    request_times: list[float] = field(default_factory=list)
    tokens_used_today: int = 0
    day_bucket: int | None = None


class RateLimiter:
    def __init__(self, max_requests_per_window: int = 20, window_seconds: float = 60.0, daily_token_ceiling: int = 200_000):
        self.max_requests_per_window = max_requests_per_window
        self.window_seconds = window_seconds
        self.daily_token_ceiling = daily_token_ceiling
        self._state: dict[str, _IpState] = defaultdict(_IpState)

    def _day_bucket(self, now: float) -> int:
        return int(now // 86400)

    def _roll_day_if_needed(self, state: _IpState, now: float) -> None:
        bucket = self._day_bucket(now)
        if state.day_bucket != bucket:
            state.day_bucket = bucket
            state.tokens_used_today = 0

    def check(self, ip: str, now: float) -> RateLimitDecision:
        state = self._state[ip]
        self._roll_day_if_needed(state, now)

        state.request_times = [t for t in state.request_times if now - t < self.window_seconds]
        if len(state.request_times) >= self.max_requests_per_window:
            return RateLimitDecision(allowed=False, reason=f"rate limit exceeded: max {self.max_requests_per_window} requests per {int(self.window_seconds)}s")

        if state.tokens_used_today >= self.daily_token_ceiling:
            return RateLimitDecision(allowed=False, reason=f"daily token ceiling of {self.daily_token_ceiling} reached for this IP")

        return RateLimitDecision(allowed=True)

    def record_request(self, ip: str, now: float, tokens_used: int = 0) -> None:
        state = self._state[ip]
        self._roll_day_if_needed(state, now)
        state.request_times.append(now)
        state.tokens_used_today += tokens_used

    def tokens_used_today(self, ip: str, now: float) -> int:
        state = self._state[ip]
        self._roll_day_if_needed(state, now)
        return state.tokens_used_today
