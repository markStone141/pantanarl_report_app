#!/usr/bin/env python3
"""Audit shared UI shell invariants across production templates and styles."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_ROOTS = (REPO_ROOT / "backend/templates", REPO_ROOT / "backend/apps")
STATIC_ROOT = REPO_ROOT / "backend/static"
LEGACY_DRAWER_PATTERN = re.compile(
    r'class="[^"]*\bbtn-inline\b[^"]*\bdashboard-drawer-toggle\b'
)
DRAWER_BUTTON_PATTERN = re.compile(
    r'<button\b[^>]*\bclass="([^"]*\bdashboard-drawer-toggle\b[^"]*)"',
    re.DOTALL,
)
FORBIDDEN_MARKERS = ("topbar-menu-toggle", "menu-collapsible")


def production_templates() -> list[Path]:
    files: set[Path] = set()
    for root in TEMPLATE_ROOTS:
        files.update(root.rglob("templates/**/*.html"))
        if root.name == "templates":
            files.update(root.rglob("*.html"))
    return sorted(files)


def relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def main() -> int:
    failures: list[str] = []
    templates = production_templates()
    drawer_buttons = 0
    app_shell_roots = 0
    btn_inline_uses = 0

    for path in templates:
        text = path.read_text(encoding="utf-8")
        path_label = relative(path)
        app_shell_roots += text.count('class="app-shell')
        btn_inline_uses += len(re.findall(r"\bbtn-inline\b", text))

        if LEGACY_DRAWER_PATTERN.search(text):
            failures.append(f"{path_label}: legacy btn-inline drawer toggle")

        for match in DRAWER_BUTTON_PATTERN.finditer(text):
            drawer_buttons += 1
            classes = match.group(1).split()
            if "ui-icon-button" not in classes:
                failures.append(f"{path_label}: drawer toggle lacks ui-icon-button")

        for marker in FORBIDDEN_MARKERS:
            if marker in text:
                failures.append(f"{path_label}: legacy marker {marker}")

    for path in sorted(STATIC_ROOT.rglob("*")):
        if path.suffix not in {".css", ".js"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for marker in FORBIDDEN_MARKERS:
            if marker in text:
                failures.append(f"{relative(path)}: legacy marker {marker}")

    print(f"templates={len(templates)}")
    print(f"app_shell_roots={app_shell_roots}")
    print(f"drawer_buttons={drawer_buttons}")
    print(f"btn_inline_uses={btn_inline_uses}")

    if failures:
        print("UI shell audit failed:")
        for failure in failures:
            print(f" - {failure}")
        return 1

    print("UI shell audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
