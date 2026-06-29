from pathlib import Path
from agent_carbon.collectors.claude_code import ClaudeCodeCollector
from agent_carbon.collectors.stubs import CodexCollector
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def test_parses_only_assistant_messages_with_usage():
    events = list(ClaudeCodeCollector(str(FIXTURES / "sample.jsonl")).collect())
    assert len(events) == 2  # la ligne user est ignorée


def test_event_fields_mapped_from_real_structure():
    events = {e.msg_id: e for e in ClaudeCodeCollector(str(FIXTURES)).collect()}
    e = events["u1"]
    assert e.provider == "anthropic"
    assert e.model == "claude-opus-4-8"
    assert e.input_tokens == 8427
    assert e.output_tokens == 287
    assert e.cache_read_tokens == 8020
    assert e.cache_creation_tokens == 7052
    assert e.project == "projA"          # basename de cwd
    assert e.session_id == "sess-A"
    assert e.client == "claude-code"     # outil client à l'origine de l'event


def test_active_seconds_from_timestamp_delta():
    # delta de 30 s entre le message user et la réponse assistant
    events = list(ClaudeCodeCollector(str(FIXTURES / "active.jsonl")).collect())
    assert len(events) == 1
    assert abs(events[0].active_seconds - 30.0) < 0.01


def test_collect_from_single_file():
    # le collecteur accepte un fichier unique (transcript de la session courante)
    f = FIXTURES / "sample.jsonl"
    events = list(ClaudeCodeCollector(str(f)).collect())
    assert len(events) == 2  # les 2 messages assistant du fichier


def test_stub_collector_raises():
    with pytest.raises(NotImplementedError):
        list(CodexCollector().collect())
