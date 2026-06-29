import pytest

from agent_carbon.dates import parse_since


def test_iso_date_kept():
    assert parse_since("2026-06-27") == "2026-06-27"


def test_french_full_year():
    assert parse_since("27/06/2026") == "2026-06-27"


def test_french_short_year():
    assert parse_since("27/06/26") == "2026-06-27"


def test_full_iso_timestamp_passthrough():
    # un timestamp ISO complet (avec heure/TZ) reste inchangé (rétro-compat)
    assert parse_since("2026-06-27T00:00:00Z") == "2026-06-27T00:00:00Z"


def test_whitespace_trimmed():
    assert parse_since("  2026-06-27  ") == "2026-06-27"


def test_unrecognized_raises():
    with pytest.raises(ValueError):
        parse_since("pas-une-date")
