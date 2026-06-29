from dataclasses import dataclass


@dataclass(frozen=True)
class InferenceEvent:
    """Un message d'inférence normalisé, neutre vis-à-vis de l'outil source."""

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    timestamp: str          # ISO 8601 UTC
    project: str
    session_id: str
    msg_id: str             # unique par message → clé d'idempotence
    active_seconds: float = 0.0  # temps actif estimé (delta depuis le message précédent)
    client: str = ""        # outil client à l'origine de l'event (claude-code, opencode…)
