from datetime import datetime

# Formats de date acceptés pour --since, normalisés en « YYYY-MM-DD ».
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y")


def parse_since(value: str) -> str:
    """Normalise une date de filtre `--since` en « YYYY-MM-DD ».

    Accepte une date simple (`2026-06-27`, `27/06/2026`, `27/06/26`) — sans
    heure ni fuseau. Un timestamp ISO 8601 complet (contenant « T ») est laissé
    tel quel (rétro-compatibilité). La comparaison en base est lexicographique :
    « 2026-06-27 » englobe toute la journée des timestamps « 2026-06-27T…Z ».

    Lève ``ValueError`` si le format n'est pas reconnu (argparse l'affiche alors
    proprement).
    """
    v = value.strip()
    if "T" in v:  # timestamp ISO complet → inchangé
        return v
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(
        f"date --since non reconnue : {value!r} "
        "(formats acceptés : 2026-06-27, 27/06/2026, 27/06/26)"
    )
