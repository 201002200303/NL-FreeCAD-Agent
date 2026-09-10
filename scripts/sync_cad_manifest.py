"""Generate / verify the packaged CAD manifest copy in the FreeCAD add-on.

The add-on is installed outside the Agent process, so the model-visible CAD
contract has to exist as a file on both sides.  Keep
`agent_service/app/cad_program/manifest.py` canonical and run:

    python scripts/sync_cad_manifest.py           # write the plugin copy
    python scripts/sync_cad_manifest.py --check   # fail (exit 1) if out of sync

`agent_service/test_cad_contract_manifest.py` calls `check()` so CI catches a
hand-edited second source.
"""

import argparse
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CANONICAL = REPO_ROOT / "agent_service" / "app" / "cad_program" / "manifest.py"
PLUGIN = REPO_ROOT / "freecad_addon" / "AICADAgent" / "cad_program" / "manifest.py"

HEADER = (
    "# GENERATED FILE - do not edit by hand.\n"
    "# Source: agent_service/app/cad_program/manifest.py\n"
    "# Regenerate: python scripts/sync_cad_manifest.py\n"
    "\n"
)


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def expected_plugin_source() -> str:
    """Exact content the packaged plugin copy must have."""
    return HEADER + _read(CANONICAL)


def check() -> list[str]:
    """Return a list of problems; empty means canonical and plugin agree."""
    if not CANONICAL.is_file():
        return [f"canonical manifest missing: {CANONICAL}"]
    if not PLUGIN.is_file():
        return [f"plugin manifest missing: {PLUGIN}"]
    if _read(PLUGIN) != expected_plugin_source():
        return [
            "plugin manifest is out of sync with the canonical copy; "
            "run: python scripts/sync_cad_manifest.py"
        ]
    return []


def write() -> None:
    PLUGIN.parent.mkdir(parents=True, exist_ok=True)
    with open(PLUGIN, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(expected_plugin_source())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="verify only; exit 1 when out of sync"
    )
    args = parser.parse_args()

    if args.check:
        problems = check()
        for problem in problems:
            print(problem)
        print("in sync" if not problems else "OUT OF SYNC")
        return 1 if problems else 0

    write()
    print(f"wrote {PLUGIN.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
