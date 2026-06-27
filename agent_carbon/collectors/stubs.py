from collections.abc import Iterator

from agent_carbon.collectors.base import Collector
from agent_carbon.models import InferenceEvent


class CodexCollector(Collector):
    """Placeholder — à implémenter quand on ajoutera Codex."""

    provider = "openai"

    def collect(self) -> Iterator[InferenceEvent]:
        raise NotImplementedError("CodexCollector pas encore implémenté")


class LocalInferenceCollector(Collector):
    """Placeholder — inférence locale (Apple Silicon), hors MVP."""

    provider = "local"

    def collect(self) -> Iterator[InferenceEvent]:
        raise NotImplementedError("LocalInferenceCollector pas encore implémenté")
