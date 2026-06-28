import os
import re

# Mapping alpha-2 → alpha-3 (ISO 3166-1) pour les zones EcoLogits courantes.
ALPHA2_TO_ALPHA3 = {
    "FR": "FRA", "DE": "DEU", "US": "USA", "GB": "GBR", "BE": "BEL",
    "CH": "CHE", "ES": "ESP", "IT": "ITA", "CA": "CAN", "NL": "NLD",
    "SE": "SWE", "NO": "NOR", "PL": "POL", "CN": "CHN", "JP": "JPN",
}

_LOCALE_COUNTRY = re.compile(r"^[a-z]{2}[_-]([A-Z]{2})")


def system_locale() -> str | None:
    for var in ("LC_ALL", "LC_CTYPE", "LANG"):
        val = os.environ.get(var)
        if val:
            return val
    return None


def detect_zone(locale_str: str | None) -> str | None:
    if not locale_str:
        return None
    m = _LOCALE_COUNTRY.match(locale_str)
    if not m:
        return None
    return ALPHA2_TO_ALPHA3.get(m.group(1))
