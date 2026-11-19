"""Exit 1 unless pyproject, the HA manifest and (if given) the release tag agree on one version."""
import json
import sys
import tomllib
from pathlib import Path


def main(argv: list[str]) -> int:
    py = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
    manifest = json.loads(Path("custom_components/framecurator/manifest.json").read_text())["version"]
    found = {"pyproject.toml": py, "manifest.json": manifest}
    if argv:
        found["tag"] = argv[0].removeprefix("v")
    if len(set(found.values())) > 1:
        print("version mismatch: " + ", ".join(f"{k} {v}" for k, v in found.items()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
