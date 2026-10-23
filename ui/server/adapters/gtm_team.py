from pathlib import Path

from ..config import configured_registry


def default_gtm_registry(home):
    path = Path(__file__).resolve().parents[2] / "gtm.desk.yaml"
    return configured_registry(path, home=home)
