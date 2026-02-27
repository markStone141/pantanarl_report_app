#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys


TARGET_SUFFIXES = {".py", ".html", ".css", ".js", ".yml", ".yaml", ".md", ".txt"}
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules"}
BOM = b"\xef\xbb\xbf"


def should_check(path: pathlib.Path) -> bool:
    if path.suffix.lower() not in TARGET_SUFFIXES:
        return False
    return not any(part in SKIP_DIRS for part in path.parts)


def main() -> int:
    root = pathlib.Path(".")
    failed: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or not should_check(path):
            continue
        try:
            with path.open("rb") as f:
                head = f.read(3)
            if head == BOM:
                failed.append(str(path))
        except OSError:
            failed.append(str(path))

    if failed:
        print("BOM detected in the following files:")
        for item in failed:
            print(f" - {item}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

