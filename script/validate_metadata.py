"""Check local packaging invariants not covered by hassfest."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """Validate JSON files and keep the advertised minimum HA version aligned."""
    for path in (ROOT / "custom_components" / "energy_owl").rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    minimum = hacs["homeassistant"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if f"| Home Assistant | {minimum} |" not in readme:
        raise SystemExit("README minimum Home Assistant version differs from hacs.json")
    print(f"Component JSON valid; minimum Home Assistant {minimum} matches README")


if __name__ == "__main__":
    main()
