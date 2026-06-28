from agent_carbon.config_detect import detect_zone, ALPHA2_TO_ALPHA3


def test_detect_zone_from_locale():
    assert detect_zone("fr_FR.UTF-8") == "FRA"
    assert detect_zone("en_US.UTF-8") == "USA"
    assert detect_zone("de_DE") == "DEU"


def test_detect_zone_unknown_country_returns_none():
    assert detect_zone("xx_ZZ.UTF-8") is None


def test_detect_zone_no_country_returns_none():
    assert detect_zone("C") is None
    assert detect_zone(None) is None


def test_mapping_covers_common_countries():
    for a3 in ("FRA", "DEU", "USA", "SWE", "NOR"):
        assert a3 in ALPHA2_TO_ALPHA3.values()
