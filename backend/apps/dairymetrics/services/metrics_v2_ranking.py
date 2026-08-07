RANKING_METRIC_OPTIONS = [
    {"key": "conversion_rate", "label": "決済率", "unit": "%"},
    {"key": "communication_rate", "label": "コミュニケーション率", "unit": "%"},
    {"key": "approach_count", "label": "合計アプローチ数", "unit": ""},
    {"key": "communication_count", "label": "合計コミュニケーション数", "unit": ""},
    {"key": "average_amount_per_active_day", "label": "1稼働あたりの平均金額", "unit": "円"},
    {"key": "average_amount_per_decision", "label": "1決済あたりの平均金額", "unit": "円"},
    {"key": "amount_stability_score", "label": "金額安定スコア", "unit": ""},
    {"key": "count_stability_score", "label": "件数安定スコア", "unit": ""},
    {"key": "support_amount", "label": "合計決済金額", "unit": "円"},
    {"key": "decision_count", "label": "合計件数", "unit": ""},
    {"key": "cs_count", "label": "CS件数", "unit": ""},
    {"key": "refugee_count", "label": "難民件数", "unit": ""},
    {"key": "increase_count", "label": "増額件数", "unit": ""},
    {"key": "increase_amount", "label": "増額金額", "unit": "円"},
    {"key": "return_count", "label": "戻り件数", "unit": ""},
    {"key": "return_amount", "label": "戻り金額", "unit": "円"},
]

WV_ONLY_RANKING_METRIC_KEYS = {"cs_count", "refugee_count"}
UN_ONLY_RANKING_METRIC_KEYS = {"amount_stability_score", "count_stability_score"}


def ranking_metric_options_for_department(department_code: str) -> list[dict]:
    return [
        option
        for option in RANKING_METRIC_OPTIONS
        if (
            (department_code == "WV" or option["key"] not in WV_ONLY_RANKING_METRIC_KEYS)
            and (department_code == "UN" or option["key"] not in UN_ONLY_RANKING_METRIC_KEYS)
        )
    ]
