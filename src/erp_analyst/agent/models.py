from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from erp_analyst.config import settings


def get_model(tier: str, provider: str | None = None):
    """"cheap" vs "strong" tiers (see build spec): start cheap, escalate to
    strong only after a repair attempt fails — most questions don't need
    the expensive model.

    `provider` defaults to settings.erp_model_provider ("anthropic" by
    default). The second provider (OpenAI) is wired through the same
    interface — anything that implements the LangChain chat model
    `.invoke([("system", ...), ("user", ...)])` contract works as a drop-in
    sql_generator/result_checker backend — but is untested against a live
    OpenAI account: no OPENAI_API_KEY was available while building this.
    See KNOWN_LIMITS.md.
    """
    if tier not in ("cheap", "strong"):
        raise ValueError(f"Unknown model tier: {tier!r}")

    provider = provider or settings.erp_model_provider
    if provider == "anthropic":
        model_id = settings.erp_model_cheap if tier == "cheap" else settings.erp_model_strong
        return ChatAnthropic(model=model_id, api_key=settings.anthropic_api_key, temperature=0, max_tokens=1024)
    if provider == "openai":
        model_id = settings.erp_openai_model_cheap if tier == "cheap" else settings.erp_openai_model_strong
        return ChatOpenAI(model=model_id, api_key=settings.openai_api_key, temperature=0, max_tokens=1024)
    raise ValueError(f"Unknown model provider: {provider!r}")
