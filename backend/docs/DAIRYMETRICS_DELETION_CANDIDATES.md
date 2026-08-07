# dairymetrics 旧機能削除記録

作成日: 2026-08-07
更新日: 2026-08-07

## 削除結果

以下の旧機能は削除済み。

- 旧 DairyMetrics ダッシュボード系 URL / view / template
- 旧入力フォーム `entry/`、旧 preview `entry-v2/`
- 旧 dairymetrics admin / 月次編集 / 旧補正登録画面
- 旧目標設定 `targets/scope/`
- demo seed command `seed_dairymetrics_demo`

削除後に以下を確認済み。

- `python manage.py test apps.dairymetrics.tests apps.dairymetrics.test_final_actuals apps.dairymetrics.test_transaction_models apps.performance.tests apps.dashboard.tests apps.reports.tests`: 235 tests OK
- `python manage.py check`: OK
- `python manage.py makemigrations --check --dry-run`: No changes detected
- `python scripts/check_no_bom.py`: OK
- `git diff --check`: OK

バックアップは `/tmp/pantanarl_dairymetrics_backup_20260807-133956` に作成し、テスト通過後に削除済み。

## 目的

`apps.dairymetrics` には、現行の決済登録、分析、振り返りレポートと、旧 DairyMetrics 画面が同居していた。現行機能を壊さず削除した対象と、残した対象を URL、テンプレート、参照状況から記録する。

## 調査方法

- `backend/apps/dairymetrics/urls.py` の URL 名を一覧化。
- `backend/apps`、`backend/templates`、`backend/static` から URL 名の厳密参照を確認。
- `views.py` の render 先テンプレートを確認。
- テンプレートの行数と用途を確認。

## 残すべき現行機能

以下は外部アプリからの導線、または現行運用で使われているため削除対象外。

| URL name | 用途 | 主な外部参照 |
| --- | --- | --- |
| `dairymetrics_login` | 決済登録アプリのログイン | `talks/login.html` |
| `dairymetrics_logout` | 決済登録アプリのログアウト | dairymetrics 内 |
| `dairymetrics_entry_v2_transaction_demo` | 現行の決済登録アプリ | `performance`、`talks`、`dashboard` |
| `dairymetrics_entry_v2_personal_setup_fields` | 決済登録の部署別入力 AJAX | dairymetrics 内 |
| `dairymetrics_transaction_reaction_update` | 決済スタンプ更新 AJAX | dairymetrics 内 |
| `dairymetrics_metrics_v2_demo` | 現行の「分析する」画面 | `performance`、`dashboard` |
| `dairymetrics_metrics_report` | 振り返りレポート | `performance` |
| `dairymetrics_metrics_report_export` | 振り返りレポート export | dairymetrics 内 |

関連テンプレート:

- `dairymetrics/login.html`
- `dairymetrics/entry_form_v2_transaction.html`
- `dairymetrics/partials/personal_setup_form.html`
- `dairymetrics/partials/department_target_form.html`
- `dairymetrics/partials/transaction_detail_card.html`
- `dairymetrics/metrics_v2.html`
- `dairymetrics/metrics_report.html`

関連 service/model:

- `models.py` は現行の実績、決済、補正、WVキャンセル、通知、スタンプが依存しているため削除しない。
- `migrations/` は既存 DB との整合性のため削除しない。
- `services/entry_context.py`、`services/entry_v2.py`、`services/metrics_v2.py`、`services/reports.py`、`services/report_exports.py`、`services/final_actuals.py`、`services/activity_state.py`、`services/reaction_notifications.py`、`services/transaction_notifications.py` は現行機能から参照されているため削除しない。

## 削除候補 A: 旧 DairyMetrics ダッシュボード系

外部アプリからの実導線がなく、dairymetrics 内で閉じている旧画面群。

| URL name | path | view | 主なテンプレート |
| --- | --- | --- | --- |
| `dairymetrics_dashboard` | `/metrics/` | `dashboard` | `dashboard.html`、`partials/dashboard_card.html` |
| `dairymetrics_member_index` | `/metrics/members/` | `member_index` | 一覧部分は view 内でHTMLを返却 |
| `dairymetrics_member_dashboard` | `/metrics/members/<id>/` | `member_dashboard` | `dashboard.html` |
| `dairymetrics_compare` | `/metrics/compare/` | `comparison_view` | `comparison.html`、`partials/comparison_panel.html` |
| `dairymetrics_compare_ranking_detail` | `/metrics/compare/ranking-detail/` | `comparison_ranking_detail` | `partials/ranking_detail_modal.html` |
| `dairymetrics_member_overview` | `/metrics/overview/` | `member_overview` | `member_overview.html` |
| `dairymetrics_member_monthly_overview` | `/metrics/monthly/` | `member_monthly_overview` | `member_monthly.html` |

削除候補テンプレート:

- `dairymetrics/dashboard.html`
- `dairymetrics/partials/dashboard_card.html`
- `dairymetrics/comparison.html`
- `dairymetrics/partials/comparison_panel.html`
- `dairymetrics/partials/member_comparison_block.html`
- `dairymetrics/partials/ranking_detail_modal.html`
- `dairymetrics/member_overview.html`
- `dairymetrics/member_monthly.html`

注意点:

- `dairymetrics_dashboard` は、現行 `metrics_v2` や `metrics_report` の未ログイン時 fallback redirect として残っている箇所がある。削除時は login redirect または `performance:index` など現行導線へ置換が必要。
- `dashboard` 系テストは `backend/apps/dairymetrics/tests.py` に多数残っている。削除する場合は旧画面テストも削除または現行仕様テストへ移行する。

## 削除候補 B: 旧入力フォーム系

現行の決済登録は `entry-v2-transaction/`。以下は旧フォームまたはプレビュー用 demo と見られる。

| URL name | path | view | 主なテンプレート |
| --- | --- | --- | --- |
| `dairymetrics_entry` | `/metrics/entry/` | `entry_form` | `entry_form.html`、`partials/entry_modal_form.html`、`partials/entry_form_fields.html` |
| `dairymetrics_entry_v2_demo` | `/metrics/entry-v2/` | `entry_form_v2_demo` | `entry_form_v2.html` |

削除候補テンプレート:

- `dairymetrics/entry_form.html`
- `dairymetrics/partials/entry_modal_form.html`
- `dairymetrics/partials/entry_form_fields.html`
- `dairymetrics/entry_form_v2.html`

注意点:

- `entry_form_v2.html` には現行 `entry-v2-transaction` と `metrics-v2` へのリンクがあるが、外部から `entry-v2/` への導線はない。
- `entry_form` は旧 `dashboard_card.html` から呼ばれているため、削除候補 A と同時に整理するのが安全。

## 削除候補 C: 旧 admin / 目標設定系

現在の管理導線は `performance`、`dashboard`、`targets` 側へ寄っている。以下は dairymetrics 内 admin として閉じている。

| URL name | path | view | 主なテンプレート |
| --- | --- | --- | --- |
| `dairymetrics_scope_target` | `/metrics/targets/scope/` | `scope_target_form` | `scope_target_form.html`、`partials/scope_target_modal_form.html` |
| `dairymetrics_admin_overview` | `/metrics/admin/` | `admin_overview` | `admin_overview.html`、`partials/admin_overview_content.html` |
| `dairymetrics_admin_ranking_overview` | `/metrics/admin/rankings/` | `admin_ranking_overview` | `admin_ranking.html` |
| `dairymetrics_admin_monthly_overview` | `/metrics/admin/monthly/` | `admin_monthly_overview` | `admin_monthly.html` |
| `dairymetrics_admin_monthly_update_cell` | `/metrics/admin/monthly/update-cell/` | `admin_monthly_update_cell` | JSON/AJAX |
| `dairymetrics_admin_monthly_bulk_update` | `/metrics/admin/monthly/bulk-update/` | `admin_monthly_bulk_update` | redirect |
| `dairymetrics_admin_monthly_comparison` | `/metrics/admin/monthly-comparison/` | `admin_monthly_comparison` | `admin_monthly_comparison.html` |
| `dairymetrics_adjustment_create` | `/metrics/admin/adjustments/new/` | `adjustment_create` | `admin_adjustment_form.html` |

削除候補テンプレート:

- `dairymetrics/scope_target_form.html`
- `dairymetrics/partials/scope_target_modal_form.html`
- `dairymetrics/admin_overview.html`
- `dairymetrics/partials/admin_overview_content.html`
- `dairymetrics/admin_ranking.html`
- `dairymetrics/admin_monthly.html`
- `dairymetrics/admin_monthly_comparison.html`
- `dairymetrics/admin_adjustment_form.html`
- `dairymetrics/partials/admin_header.html`

注意点:

- `admin_header.html` には現行の決済入力、分析リンクも含まれるが、旧 admin テンプレート専用の partial と見られる。
- 補正実績登録の現行導線は `performance` 側にあるため、`dairymetrics_adjustment_create` は削除候補。ただし、既存テストに依存が残っているためテスト整理が必要。

## 削除候補 D: demo seed command

| ファイル | 理由 |
| --- | --- |
| `backend/apps/dairymetrics/management/commands/seed_dairymetrics_demo.py` | ローカル demo 用の seed command。現行本番運用では不要と見られる。 |

注意点:

- 開発者がローカル視覚確認に使っている可能性はある。
- 削除前に README、docs、CI、手順書から参照がないか再確認する。

## すぐ削除しない方がよいもの

- `models.py`: 現行の決済登録、分析、補正、WVキャンセル、通知、スタンプが依存。
- `migrations/`: 既存 DB と Supabase 本番 DB の整合性に必要。
- `forms.py`: `DairymetricsV2TransactionForm`、ログインフォーム、目標フォームなどが現行から参照。
- `auth.py`: `performance` 側のログインにも参照あり。
- `selectors.py`: 現行分析やレポートの集計補助として残す。
- `services/*`: 現行機能の依存が残っているため、削除ではなく分割・責務整理の対象。

## 推奨削除順

1. 旧 `dairymetrics_dashboard` への fallback redirect を現行導線へ置換する。
2. 削除候補 A の URL を一時的に 404 または現行ページ redirect に変更し、外部影響がないかテストする。
3. 旧 dashboard / comparison / member overview テンプレートと関連テストを削除する。
4. 削除候補 B の旧入力フォームを削除する。
5. 削除候補 C の旧 admin / 目標設定画面を削除する。
6. demo seed command の参照有無を確認してから削除する。
7. `views.py` から未使用 view を削除し、import と helper を整理する。
8. `services/entry_context.py` などに残る demo 命名を、現行機能名へ rename する。

## リファクタリング候補

削除後も `dairymetrics` は現行機能だけで大きい。削除作業と混ぜず、別作業として以下を実施するのが安全。

- `views.py` から決済登録 view、分析 view、レポート view をモジュール分割する。
- `entry_form_v2_transaction.html` は 1200 行超のため、表示セクションごとに partial 化する。
- `services/metrics_v2.py` は 900 行超のため、集計、ランキング、チャート、期間解決を分ける。
- `entry_context.py` の `demo` 命名を現行運用名へ変更する。

## 残リスク

- 旧画面への直接 URL アクセスを利用しているユーザーがいる場合、外部導線検索だけでは検出できない。
- 削除対象の view に現行 service と同じ helper が混在している可能性があるため、view 削除時は import 単位で機械的に未使用確認する必要がある。
- 旧テストを一括削除すると回帰検知が弱くなるため、現行の決済登録、分析、レポートで同等の受け入れ条件を維持してから削除する。
