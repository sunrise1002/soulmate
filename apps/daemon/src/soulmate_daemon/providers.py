"""Daemon composition for replaceable model providers."""

from soulmate_llm_providers import (
    EgressPolicy,
    LLMProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
)

from soulmate_daemon.config import Settings


def build_provider(settings: Settings) -> LLMProvider:
    policy = EgressPolicy(settings.privacy.mode)
    if settings.llm.provider == "ollama":
        return OllamaProvider(
            base_url=str(settings.llm.ollama.base_url),
            model=settings.llm.ollama.model,
            policy=policy,
        )
    configured = settings.llm.openai_compatible
    return OpenAICompatibleProvider(
        base_url=str(configured.base_url),
        model=configured.model,
        api_key=None if configured.api_key is None else configured.api_key.get_secret_value(),
        policy=policy,
    )
