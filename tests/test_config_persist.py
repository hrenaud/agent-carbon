import os
from ecologits.utils.range_value import RangeValue
from agent_carbon.config import Config


def test_defaults():
    c = Config()
    assert c.electricity_mix_zone is None
    assert c.datacenter_pue == RangeValue(min=1.1, max=1.5)
    assert c.datacenter_wue == 0.0
    assert c.model_params == {}
    assert c.throughput_tok_s == 50.0


def test_load_missing_file_returns_defaults(tmp_path):
    c = Config.load(str(tmp_path / "absent.json"))
    assert c.electricity_mix_zone is None
    assert c.model_params == {}


def test_load_ignores_unknown_keys(tmp_path):
    """Une clé inconnue (version future, édition manuelle) ne fait pas planter
    le chargement : elle est ignorée, les champs connus restent lus."""
    path = tmp_path / "config.json"
    path.write_text(
        '{"electricity_mix_zone": "FRA", "future_option": 42}',
        encoding="utf-8",
    )
    c = Config.load(str(path))
    assert c.electricity_mix_zone == "FRA"


def test_save_then_load_roundtrip(tmp_path):
    path = str(tmp_path / "config.json")
    c = Config(
        electricity_mix_zone="FRA",
        datacenter_pue=RangeValue(min=1.2, max=1.2),
        datacenter_wue=0.3,
        model_params={"ollama/qwen2.5:7b": {"active": 7e9, "total": 7e9,
                                            "arch": "dense", "source": "user"}},
    )
    c.save(path)
    loaded = Config.load(path)
    assert loaded.electricity_mix_zone == "FRA"
    assert loaded.datacenter_pue == RangeValue(min=1.2, max=1.2)
    assert loaded.datacenter_wue == 0.3
    assert loaded.model_params["ollama/qwen2.5:7b"]["total"] == 7e9


def test_config_roundtrips_hf_unresolved(tmp_path):
    """M1b : le cache négatif HF est persisté dans config.json."""
    p = str(tmp_path / "config.json")
    cfg = Config(hf_unresolved={"ollama/org/x": "2026-07-02T00:00:00+00:00"})
    cfg.save(p)
    assert Config.load(p).hf_unresolved == {"ollama/org/x": "2026-07-02T00:00:00+00:00"}
