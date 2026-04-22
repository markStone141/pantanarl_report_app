from django.shortcuts import render

from .sample_content import LANGUAGE_OPTIONS, SAMPLE_TOPICS


def monthly_guide_index(request):
    default_language = "en"
    language_labels = {item["code"]: item["label"] for item in LANGUAGE_OPTIONS}
    initial_sections = []
    for topic in sorted(SAMPLE_TOPICS, key=lambda item: item["sort_order"]):
        selected_translation = topic["translations"].get(default_language) or next(
            iter(topic["translations"].values())
        )
        japanese_translation = topic["translations"].get("ja") or selected_translation
        initial_sections.append(
            {
                "slug": topic["slug"],
                "selected_title": selected_translation["title"],
                "selected_body": selected_translation["body"],
                "japanese_title": japanese_translation["title"],
                "japanese_body": japanese_translation["body"],
            }
        )

    return render(
        request,
        "monthly_guide/index.html",
        {
            "language_options": LANGUAGE_OPTIONS,
            "default_language": default_language,
            "default_language_label": language_labels[default_language],
            "initial_sections": initial_sections,
            "guide_payload": {
                "languages": LANGUAGE_OPTIONS,
                "topics": SAMPLE_TOPICS,
            },
        },
    )
