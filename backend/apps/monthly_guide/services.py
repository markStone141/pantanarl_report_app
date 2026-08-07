from __future__ import annotations


def build_initial_sections(*, topics, default_language: str) -> list[dict[str, str]]:
    sections = []
    for topic in sorted(topics, key=lambda item: item["sort_order"]):
        selected_translation = topic["translations"].get(default_language) or next(
            iter(topic["translations"].values())
        )
        japanese_translation = topic["translations"].get("ja") or selected_translation
        sections.append(
            {
                "slug": topic["slug"],
                "selected_title": selected_translation["title"],
                "selected_body": selected_translation["body"],
                "japanese_title": japanese_translation["title"],
                "japanese_body": japanese_translation["body"],
            }
        )
    return sections
