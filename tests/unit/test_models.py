import pytest
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from erp_analyst.agent.models import get_model
from erp_analyst.config import settings


@pytest.fixture(autouse=True)
def _dummy_openai_key(monkeypatch):
    # ChatOpenAI (unlike ChatAnthropic) refuses to construct with an empty
    # key — a placeholder is enough to prove provider/tier selection since
    # no real call happens here.
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-dummy")


def test_defaults_to_the_anthropic_provider():
    model = get_model("cheap")
    assert isinstance(model, ChatAnthropic)


def test_an_explicit_openai_provider_returns_a_chat_openai_instance():
    model = get_model("cheap", provider="openai")
    assert isinstance(model, ChatOpenAI)


def test_cheap_and_strong_tiers_select_different_anthropic_models():
    cheap = get_model("cheap", provider="anthropic")
    strong = get_model("strong", provider="anthropic")
    assert cheap.model != strong.model


def test_cheap_and_strong_tiers_select_different_openai_models():
    cheap = get_model("cheap", provider="openai")
    strong = get_model("strong", provider="openai")
    assert cheap.model_name != strong.model_name


def test_an_unknown_tier_raises():
    with pytest.raises(ValueError, match="Unknown model tier"):
        get_model("medium")


def test_an_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown model provider"):
        get_model("cheap", provider="cohere")
