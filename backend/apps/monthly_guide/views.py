from django.shortcuts import render

from .sample_content import LANGUAGE_OPTIONS, SAMPLE_TOPICS


def monthly_guide_index(request):
    default_language = "ja"
    initial_sections = []
    for topic in sorted(SAMPLE_TOPICS, key=lambda item: item["sort_order"]):
        translation = topic["translations"].get(default_language) or next(
            iter(topic["translations"].values())
        )
        initial_sections.append(
            {
                "slug": topic["slug"],
                "title": translation["title"],
                "body": translation["body"],
            }
        )

    return render(
        request,
        "monthly_guide/index.html",
        {
            "language_options": LANGUAGE_OPTIONS,
            "default_language": default_language,
            "initial_sections": initial_sections,
            "guide_payload": {
                "languages": LANGUAGE_OPTIONS,
                "topics": SAMPLE_TOPICS,
            },
        },
    )

