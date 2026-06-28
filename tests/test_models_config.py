from agent_carbon.models import InferenceEvent
from agent_carbon.config import Config


def test_inference_event_holds_normalized_fields():
    e = InferenceEvent(
        provider="anthropic", model="claude-opus-4-8",
        input_tokens=8427, output_tokens=287,
        cache_creation_tokens=7052, cache_read_tokens=8020,
        timestamp="2026-06-27T10:08:45.619Z", project="agent-carbon",
        session_id="sess-1", msg_id="uuid-1",
    )
    assert e.output_tokens == 287
    assert e.session_id == "sess-1"


def test_config_defaults():
    c = Config()
    assert c.electricity_mix_zone is None
    assert c.throughput_tok_s == 50.0
    assert c.model_aliases == {}
    assert c.local_wh_per_token is None
