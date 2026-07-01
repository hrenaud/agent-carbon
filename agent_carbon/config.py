import json
import os
from dataclasses import asdict, dataclass, field, fields

from ecologits.utils.range_value import RangeValue

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.agent-carbon/config.json")


@dataclass
class Config:
    """Constantes maison persistées dans ~/.agent-carbon/config.json."""

    electricity_mix_zone: str | None = None          # None = non renseigné
    throughput_tok_s: float = 50.0
    model_aliases: dict[str, str] = field(default_factory=dict)
    datacenter_pue: RangeValue = field(
        default_factory=lambda: RangeValue(min=1.1, max=1.5))
    datacenter_wue: float = 0.0
    model_params: dict[str, dict] = field(default_factory=dict)
    local_wh_per_token: float | None = None

    @classmethod
    def load(cls, path: str = DEFAULT_CONFIG_PATH) -> "Config":
        if not os.path.exists(path):
            return cls()
        with open(path) as fd:
            data = json.load(fd)
        pue = data.get("datacenter_pue")
        if isinstance(pue, dict):
            data["datacenter_pue"] = RangeValue(min=pue["min"], max=pue["max"])
        # Ignorer les clés inconnues (version future, édition manuelle) plutôt
        # que planter tout le CLI sur un TypeError.
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: str = DEFAULT_CONFIG_PATH) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        data = asdict(self)
        data["datacenter_pue"] = {"min": self.datacenter_pue.min,
                                  "max": self.datacenter_pue.max}
        with open(path, "w") as fd:
            json.dump(data, fd, indent=2, ensure_ascii=False)
