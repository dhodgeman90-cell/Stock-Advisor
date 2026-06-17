"""Build-hygiene gate (spec §7): fail the build if the produced dist/ contains any of
the owner's private artifacts. The shipped app must contain ZERO personal data.

find_forbidden(dist_dir) returns a list of human-readable problems ([] == clean).
Run as a CLI after PyInstaller:  python scripts/verify_build.py dist/StockAdvisor
Exits 1 (and prints the problems) if anything leaked, so build_app.ps1 aborts.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Secret env-var names / owner identifiers that must NEVER appear in a shipped file.
SECRET_MARKERS = (
    "ANTHROPIC_API_KEY", "SNAPTRADE_", "EMAIL_PASSWORD", "FMP_API_KEY",
    "dhodgeman90@gmail.com",
)
# Files that are private regardless of where they sit in the tree.
FORBIDDEN_FILENAMES = (".env", ".env.bak")
# Owner dirs that must never be bundled: 'data'/'reports'/'logs' hold generated data,
# and 'config' is the owner's REAL (non-default) config dir — only 'defaults' may ship.
FORBIDDEN_DIR_NAMES = ("data", "reports", "logs", "config")
# Project config files that may ONLY ship as bundled defaults (under a 'defaults' dir).
CONFIG_BASENAMES = (
    "watchlist.yaml", "watchlist_broad.yaml", "positions.yaml", "exits.yaml",
    "weights.yaml", "adjudicator.yaml", "signals.yaml", "integrations.yaml",
)
# Secret-marker scan covers ONLY these text-ish extensions; .py/.log/.toml/.conf and
# binary/wheel files are NOT scanned. Secrets-in-binaries (the frozen PYZ) are guarded by
# design instead: no secret literals live in the source tree, so none can be frozen in.
TEXT_SUFFIXES = (".env", ".yaml", ".yml", ".json", ".txt", ".cfg", ".ini", ".md")


def find_forbidden(dist_dir: str | Path) -> list[str]:
    dist = Path(dist_dir)
    if not dist.is_dir():
        return [f"dist dir does not exist or is not a directory: {dist_dir}"]
    problems: list[str] = []
    for p in dist.rglob("*"):
        rel = p.relative_to(dist)
        if p.is_dir():
            if p.name in FORBIDDEN_DIR_NAMES:
                problems.append(f"private runtime dir bundled: {rel}")
            continue
        if p.name.lower() in FORBIDDEN_FILENAMES:
            problems.append(f"env/secret file bundled: {rel}")
            continue
        if p.name.lower() in CONFIG_BASENAMES and "defaults" not in rel.parts:
            problems.append(f"non-default project config bundled: {rel}")
        if p.suffix.lower() in TEXT_SUFFIXES:
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for marker in SECRET_MARKERS:
                if marker in text:
                    problems.append(f"secret marker {marker!r} found in {rel}")
                    break
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python scripts/verify_build.py <dist_dir>")
        return 2
    problems = find_forbidden(argv[1])
    if problems:
        print("BUILD HYGIENE FAILED — owner-private artifacts found in the bundle:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("build hygiene OK — no owner-private artifacts in the bundle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
