from abc import ABC, abstractmethod
from collections.abc import Iterator

from agent_carbon.models import InferenceEvent


class Collector(ABC):
    """Transforme une source spécifique à un outil en InferenceEvent normalisés."""

    provider: str = ""

    @abstractmethod
    def collect(self) -> Iterator[InferenceEvent]:
        ...
