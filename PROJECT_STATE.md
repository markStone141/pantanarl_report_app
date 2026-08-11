# Project State

最終更新日: 2026-08-11

## 現在のフェーズ

- 開発運用整備

## プロジェクト全体の目標

- Report App、実績管理、決済入力、分析、通知、関連アプリを安全に保守・拡張できる状態にする。
- 仕様、設計、実装、テスト、監査、UI、運用判断をロールごとに分離し、作業の見落としを減らす。

## 完了した作業

- AI作業ログの標準ファイルを追加。
- 機密情報をログに残さない運用ルールを追加。
- ループエンジニアリング工程を文書化。
- ロール間Handoff JSONを文書化。
- `requirements_agent`、`test_designer`、`test_agent`、`test_auditor`、`frontend_interaction`、`ui_designer`、`project_manager`、`refactor_auditor` を追加。
- アプリ単位見直しの初回として `accounts` のログイン認証処理を service 層へ切り出し、対象テストを確認。
- `mail` のGmail API低レベル処理を専用モジュールへ分離し、既存送信サービスの互換性を対象テストで確認。
- `reports` の報告フォーム行データ処理を service 層へ分離し、対象テストで投稿・編集・履歴表示の互換性を確認。
- `targets` の部署・指標設定、状態ラベル、月/路程状態判定を service 層へ分離し、対象テストで互換性を確認。
- `monthly_guide` の初期セクション生成を service 層へ分離し、対象テストで互換性を確認。
- `common` の補正実績集計ロジックを共通化し、`targets` / `reports` / `dashboard` の対象テストで互換性を確認。
- `dashboard` のメールテンプレート用残目標計算を表示 service へ分離し、対象テストで互換性を確認。
- `dashboard` のメンバー登録・編集・一覧検索・一括管理の補助処理を service 層へ分離し、対象テストで互換性を確認。
- `dashboard` の部署管理・目標指標管理のフォーム初期化と選択状態解決を service 層へ分離し、対象テストで互換性を確認。
- `mosaic` の接客ログ保存補助処理を service 層へ分離し、独立アプリとして対象テストで互換性を確認。
- `dairymetrics` の新規決済通知・スタンプ通知から本日の全体決済一覧へ自動展開・スクロールする導線を修正し、展開中の「もっと見る」ボタンを非表示にした。
- `talks` の一覧検索、未読・お気に入り状態付与、ページングcontext構築を selector 層へ分離し、投稿者表示ルールを service 層へ共通化した。
- `testimony` の記事一覧クエリ、検索・並び替え条件、フィルターcontext構築を selector 層へ分離し、記事一覧とお気に入り一覧のViewを薄くした。
- `performance` のメニュー生成、メンバー詳細ページのナビゲーション、戻り先URL補助、編集可否判定を navigation service へ分離した。
- `dairymetrics` の現行機能と旧画面をURL参照単位で監査し、削除候補を `backend/docs/DAIRYMETRICS_DELETION_CANDIDATES.md` に整理した。
- `dairymetrics` の旧 dashboard、旧 entry、旧 admin、旧目標設定、demo seed command を削除し、現行の決済登録・分析・振り返りレポートに絞った。
- `dairymetrics` の分析・振り返りレポート view を `views_metrics.py` へ分割し、`views.py` を薄くし始めた。
- `dairymetrics` の決済登録テンプレートから上部メニューと通知ブロックを partial 化した。
- `dairymetrics` の `metrics_v2` service からランキング定義を `metrics_v2_ranking.py` へ分離した。
- `dairymetrics` の決済登録 view から固定選択肢と partial render helper を分離した。
- `dairymetrics` の決済登録テンプレートから決済入力フォーム section を partial 化した。
- `dairymetrics` の `metrics_v2` service からランキング payload 生成を `metrics_v2_ranking.py` へ分離した。
- `performance` の現状を監査し、巨大化したView/Form/Testの責務分離計画を `backend/docs/PERFORMANCE_REFACTOR_PLAN.md` に整理した。
- `performance` の表示フォーマット処理と期間/路程scope解決を `services/formatters.py` / `services/scopes.py` へ分離し、対象テストで互換性を確認した。
- `performance` の管理者ダッシュボードで、本日の決済・送信メールを件数付きタブの「本日の記録」に統合し、今日の情報から目標達成率へ進む表示密度を改善した。
- `performance` の管理者ダッシュボードに共通セクション見出し、サマリーカード、活動状態カードの表示規則を導入し、青を基調に影と半透明表現を抑えた試作へ更新した。
- `performance` の管理者ダッシュボードで、目標達成カード、全体実績推移、有効メンバー一覧にも共通セクション・内側カードの表示規則を展開した。
- `performance` の管理者ダッシュボード／過去実績snapshot構築と関連メンバーカード集計を `services/dashboard_snapshots.py` へ分離し、Viewを表示制御中心へ縮小した。
- `performance` の今日の決済・送信メール明細row生成を `services/today_details.py` へ分離した。

## 進行中の作業

- アプリ単位の構成、責務、依存、テスト見直し。`performance` リファクタリング計画は8工程中3工程まで完了。
- 管理者ダッシュボードの主要セクションへのUI部品統一は試作済み。利用者確認後に、他画面への展開範囲を決める。

## 確定事項

- 通常ログは `logs/execution.json`、エラーログは `logs/errors.json`、直近要約は `logs/latest-summary.md` に記録する。
- 機密情報を含む可能性があるログは通常ログに入れない。
- 要件が曖昧な場合は `requirements_agent` で整理してから計画へ進む。
- UI変更時は `ui_designer` の観点を通す。
- UI操作、AJAX、画面状態、アニメーションの実装時は `frontend_interaction` の観点を通す。
- テスト設計、テスト実行・分類、テスト監査は別ロールとして扱う。
- リファクタリング監査は `refactor_auditor` として扱い、外部仕様変更と混在させない。
- 大規模な責務分離や構成変更は、承認なしに実装せず提案に留める。
- `project_manager` は、新機能完了、3ファイル以上の変更、類似処理追加、巨大ファイル化、新規フォルダや層の追加、既存コード依存の増加がある場合に `refactor_auditor` を呼ぶ。
- 長期化、範囲超過、仕様判断待ち、原因不明のテスト失敗が発生した場合は `HANDOFF.md` を作成し、状態を `paused` にして統括へ返す。

## 未決事項

- 承認済み要件、設計書、タスク一覧、意思決定ログ、テスト結果をどのファイルへ集約するか。
- `PROJECT_STATE.md` の更新頻度を作業単位、PR単位、リリース単位のどれにするか。
- `dashboard/views.py` は818行まで縮小したが、部署管理の保存処理本体・メールテンプレート生成を別作業として追加分割する余地がある。
- `performance/views.py` はsnapshot構築と今日の明細の分離後も、メンバー個別画面、補正実績、過去入力、AJAXが混在している。

## ブロッカー

- なし。

## 依存関係

- 開発工程ルールは `AGENTS.md` と `backend/docs/LOOP_ENGINEERING_GUIDE.md` を参照する。
- 作業ログは `backend/scripts/log_ai_work.py` を使う。

## 次に行う作業

- `performance` リファクタリング計画の工程4として、`dashboard_snapshots.py` 内のメンバーカード責務と部署ごとのクエリ数を監査し、`member_cards.py` へ再分離する範囲を決める。

## 参照

- `AGENTS.md`
- `backend/docs/LOOP_ENGINEERING_GUIDE.md`
- `logs/latest-summary.md`
