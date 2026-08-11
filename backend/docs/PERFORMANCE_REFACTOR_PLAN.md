# Performance Refactor Plan

作成日: 2026-08-07

## 目的

`apps.performance` は現行の実績管理アプリとして利用中のため、外部から見えるURL、画面表示、権限、UN/WV分岐、補正実績の扱いを変えずに、巨大化したViewとテストを責務単位へ分割する。

今回の作業範囲は現状把握と分割計画までとし、実装変更は次フェーズで小さく進める。

## 現状

- `backend/apps/performance/views.py`: 2,893行。認証、ダッシュボード、過去実績、メンバー個別画面、AJAX、編集/削除、過去入力、補正実績が同居している。
- `backend/apps/performance/forms.py`: 412行。フィルター、過去入力、日次編集、補正実績登録のフォームが同居している。
- `backend/apps/performance/tests.py`: 2,900行。全機能の回帰テストが1ファイルに集中している。
- テンプレート合計は2,994行。`adjustments.html`, `member_detail.html`, `past_entry_create.html`, `index.html`, `history.html` が大きい。
- 既存serviceは `activity_reminders`, `admin_entries`, `closeout_notes`, `member_details`, `navigation`, `past_entries`, `progress`, `trends` に分かれているが、View内にまだコンテキスト構築と集計補助が多く残っている。

## Viewの主な責務

| 範囲 | 主な関数 | 現状の問題 |
| --- | --- | --- |
| 認証/権限 | `require_performance_roles`, `performance_login`, `performance_logout` | View内に残っているが小さい。優先度は低い。 |
| 一覧フィルター | `_filtered_entries_queryset`, `_filtered_adjustments_queryset`, `_combined_adjustment_list_rows` | query組み立てと表示row変換がViewにある。 |
| 期間/路程解決 | `_resolve_current_period`, `_resolve_history_period_from_request`, `_resolve_performance_history_scope` | Active路程の扱いが重要な業務ルールなので、専用serviceへ寄せるべき。 |
| 管理者ダッシュボード | `_build_performance_dashboard_snapshot`, `performance_index` | 今日の実績、活動中/終了、全体進捗、メンバーカード生成が同居している。 |
| 過去実績全体 | `_build_performance_history_snapshot`, `performance_history` | ダッシュボードと似た集計・カード生成が重複している。 |
| メンバー画面 | `_build_member_dashboard_context`, `_build_member_history_context`, 関連AJAX | 500行規模のcontext構築がView内に残っている。 |
| 今日の明細 | `_department_today_transaction_detail_rows`, `_department_today_mail_detail_rows` | 管理者ダッシュボード用の表示row生成がView内にある。 |
| 管理者エントリー | `performance_admin_entries`, `performance_entry_edit/delete`, `performance_transaction_edit/delete`, `performance_summary_delete` | 一部service化済みだが、編集・削除の保存処理はView内。 |
| 過去実績入力 | `performance_past_entry_create`, `performance_past_entry_member_options` | 保存処理はservice化済み。Viewはフォーム制御とリダイレクトが中心。 |
| 補正実績 | `performance_adjustments`, `performance_adjustment_delete`, `performance_cancellation_delete` | フィルター、UN/WV分岐、メンバー候補、AJAX一覧、保存処理が1関数に集中。 |
| フォーマット | `_count_text`, `_amount_text`, `_final_count_text`, `_final_amount_text` | 複数画面で使う表示ルールがView private関数になっている。 |

## DBアクセス上の注意点

- `_collect_member_totals_by_department` と `_collect_member_latest_entries_by_department` は部署ごとにクエリを回す。部署数は少ない前提なら許容しやすいが、将来的に部署が増えるなら一括取得へ寄せる余地がある。
- `build_member_dashboard_entry_rows` はentry取得後に各entryのtransactionsを使う。`prefetch_related("transactions")` は入っているが、ループ内で `entry.transactions.all().order_by(...)` を呼んでおり、prefetchが効かず追加クエリになる可能性がある。分割時に `Prefetch` で順序付き取得へ直す候補。
- `performance_adjustments` のメンバー候補生成は全active memberを毎回読み込む。AJAX/autofill用途なので、部署選択時に必要分だけ返すAPIへ分ける候補。
- `build_adjustment_totals_map` は `WVMetricCancellation` を扱っていない。現行表示仕様でキャンセルを補正扱いに含める箇所は、別集計または共通補正集計に寄せる必要がある。
- Active路程は `current_active_period` を使う箇所と、リクエスト指定periodを許可する箇所が混在しやすい。現行路程参照と過去路程参照の関数境界を分ける。

## 分割方針

URL名とテンプレート名は維持する。まず `views.py` のprivate関数を責務単位のserviceへ移し、View関数は「権限、フォーム、service呼び出し、render/redirect」だけに近づける。

### 優先度1: 期間/表示フォーマットの共通化

追加候補:

- `apps/performance/services/scopes.py`
- `apps/performance/services/formatters.py`

移動候補:

- `PerformanceHistoryScope`
- `_resolve_current_period`
- `_resolve_history_period_from_request`
- `_resolve_performance_history_scope`
- `_period_range_label`
- `_period_display_label`
- `_count_text`
- `_amount_text`
- `_field_count_text`
- `_field_amount_text`
- `_final_count_text`
- `_final_count_subtext`
- `_final_count_value`
- `_final_amount_text`

理由:

- Active路程バグの再発防止に直結する。
- 他serviceから使える純粋関数が多く、移動リスクが比較的低い。
- テスト対象は既存の `active_period`, `finished_period_param`, `history` 系をそのまま使える。

### 優先度2: 管理者ダッシュボード/過去実績snapshotの分離

追加候補:

- `apps/performance/services/dashboard_snapshots.py`
- `apps/performance/services/member_cards.py`
- `apps/performance/services/today_details.py`

移動候補:

- `_build_performance_dashboard_snapshot`
- `_build_performance_history_snapshot`
- `_build_activity_member_rows`
- `_build_active_member_cards`
- `_build_scoped_member_cards`
- `_resolve_member_department_pairs`
- `_collect_member_totals_by_department`
- `_collect_member_latest_entries_by_department`
- `_build_member_recent_metrics`
- `_department_today_transaction_detail_rows`
- `_department_today_mail_detail_rows`
- `_build_department_today_detail_context`

理由:

- `performance_index` と `performance_history` を薄くできる。
- Active/Finished路程の扱いと全体実績表示の責務を閉じ込められる。
- DBアクセス改善を同時に検討しやすい。

### 優先度3: メンバー個別ページのcontext分離

追加候補:

- `apps/performance/services/member_pages.py`
- `apps/performance/services/member_ajax.py`

移動候補:

- `_build_member_dashboard_context`
- `_build_member_history_context`
- `_render_member_history_day_detail_response`
- `_render_member_history_list_response`
- `_render_member_day_detail_response`
- `_render_member_recent_detail_response`

理由:

- 個人ダッシュボード、過去実績、管理者からの閲覧、readonly分析画面が絡むため、権限と戻り先URLの回帰リスクが高い。
- 先にformatters/scopesを分けてから行う方が安全。

### 優先度4: 補正実績の分離

追加候補:

- `apps/performance/services/adjustments.py`
- `apps/performance/services/adjustment_options.py`
- `apps/performance/forms_adjustments.py`

移動候補:

- `_adjustment_source_types_matching_query`
- `_adjustment_search_filter`
- `_filtered_adjustments_queryset`
- `_filtered_adjustments_list_queryset`
- `_filtered_cancellations_list_queryset`
- `_adjustment_list_row`
- `_cancellation_list_row`
- `_combined_adjustment_list_rows`
- `PerformanceMetricAdjustmentForm`
- `PerformanceAdjustmentListFilterForm`

理由:

- UN/WV/キャンセル/UN活動コード/autofillが集中しており、今後も変更が入りやすい。
- ただし保存先が `MetricAdjustment` と `WVMetricCancellation` で分岐するため、最初から大きく動かすと危険。まずqueryと表示row、その後form保存ロジックの順に分ける。

### 優先度5: forms.pyとtests.pyの分割

追加候補:

- `apps/performance/forms_filters.py`
- `apps/performance/forms_entries.py`
- `apps/performance/forms_adjustments.py`
- `apps/performance/tests/test_dashboard.py`
- `apps/performance/tests/test_member_pages.py`
- `apps/performance/tests/test_admin_entries.py`
- `apps/performance/tests/test_adjustments.py`
- `apps/performance/tests/test_past_entries.py`
- `apps/performance/tests/test_reminders.py`

進め方:

- 互換性のため、まず既存 `forms.py` は各分割ファイルからimportするファサードとして残す。
- テストは先に移動だけ行い、期待値変更はしない。
- テストpackage化はDjangoのtest discoveryに影響するため、1回の変更で小さく確認する。

## 推奨実施順

| 工程 | 作業 | 状態 |
|---|---|---|
| 1 | `services/formatters.py` と `services/scopes.py` を追加し、純粋関数だけ移動する | 完了 |
| 2 | `performance_index` / `performance_history` のsnapshot構築を `dashboard_snapshots.py` へ移す | 完了 |
| 3 | 今日の決済明細/送信メールdetail rowを `today_details.py` へ移す | 完了 |
| 4 | メンバーカード生成を `member_cards.py` へ移し、部署ごとのクエリを確認する | 完了 |
| 5 | メンバー個別/過去実績contextを `member_pages.py` へ移す | 完了 |
| 6 | 補正実績のquery/row生成を `adjustments.py` へ移す | 完了 |
| 7 | 補正フォームを `forms_adjustments.py` へ移し、`forms.py` は互換importにする | 完了 |
| 8 | tests.pyを機能別に分割する | 次工程 |

工程2ではメンバーカード生成も `dashboard_snapshots.py` へ一時的に移動済み。工程4では、
`member_cards.py` へ再分離する前に、責務境界と部署ごとのクエリ数を監査する。

工程4ではカード生成、メンバーの部署解決、対象期間メンバー抽出を
`services/member_cards.py` へ分離した。同一部署のメンバーは一括集計されるため、
メンバー人数に比例するN+1はない。管理者ダッシュボードのカード集計は、部署ごとに
月累計3集計、路程累計3集計、最近実績1取得、最近実績の補正1集計を行う。
部署数には比例するが、UN/WVとキャンセルを含む既存の業務集計境界を維持するため、
この工程では複数部署をまたぐ一括集計へ変更しない。必要になった場合は
`apps.dairymetrics.services.final_actuals` に部署別一括APIを設計する別工程として扱う。

工程5ではメンバー個別ダッシュボードと過去実績のcontext構築を
`services/member_pages.py` へ分離した。権限decorator、POST保存、render、AJAX応答は
Viewに残し、URL、テンプレート、contextキー、管理者・本人・readonlyの表示仕様を維持した。

工程6では補正実績とWVキャンセルの検索query、一覧表示row生成、両recordの結合と
並び順を `services/adjustments.py` へ分離した。フォーム制御、保存・削除、ページング、
AJAX/HTML応答、メンバー候補生成はViewに残し、UN/WV分岐、検索条件、URL、表示仕様を維持した。

工程7では `PerformanceAdjustmentListFilterForm` と `PerformanceMetricAdjustmentForm` を
`forms_adjustments.py` へ分離した。既存の `forms.py` は両クラスを再公開するファサードとして
残し、View・テスト・外部コードの従来import経路、フォームフィールド、検証、保存仕様を維持した。

## 検証方針

各ステップごとに最低限以下を実行する。

```bash
cd backend
source .venv/bin/activate
python manage.py test apps.performance.tests
python manage.py check
python scripts/check_no_bom.py
git diff --check
```

モデル変更は予定しないため、通常はmigration不要。ただしフォーム分割やservice分割でimport漏れが起きやすいため、`manage.py check` は毎回実行する。

## 次の実装候補

最初の実装単位は `formatters.py` と `scopes.py` の追加が妥当。理由は、DB保存や画面操作に触れず、Active路程の業務ルールを明確に分けられるため。
