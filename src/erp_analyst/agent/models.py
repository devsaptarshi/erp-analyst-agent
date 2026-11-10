from langchain_anthropic import ChatAnthropic

from erp_analyst.config import settings


def get_model(tier: str) -> ChatAnthropic:
    """"cheap" vs "strong" tiers (see build spec): start cheap, escalate to
    strong only after a repair attempt fails — most questions don't need
    the expensive model."""
    if tier not in ("cheap", "strong"):
        raise ValueError(f"Unknown model tier: {tier!r}")
    model_id = settings.erp_model_cheap if tier == "cheap" else settings.erp_model_strong
    return ChatAnthropic(model=model_id, api_key=settings.anthropic_api_key, temperature=0, max_tokens=1024)
