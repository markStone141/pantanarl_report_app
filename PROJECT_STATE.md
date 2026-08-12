# Project State

最終更新日: 2026-08-12

## 現在のフェーズ

- 全アプリUI展開・工程10完了: PUSH・公開環境確認待ち

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
- `performance` のメンバーカード生成と対象メンバー・部署解決を `services/member_cards.py` へ分離し、同一部署内でメンバー人数に比例するN+1がないことを確認した。
- `performance` のメンバー個別ダッシュボード・過去実績context構築を `services/member_pages.py` へ分離し、Viewを権限・保存・応答制御中心へ縮小した。
- `performance` の補正実績・WVキャンセルの検索queryと一覧表示row生成を `services/adjustments.py` へ分離した。
- `performance` の補正一覧・登録フォームを `forms_adjustments.py` へ分離し、既存 `forms.py` のimport互換性を維持した。
- `performance` の単一 `tests.py` を機能別の6テストモジュールへ分割し、91件のテスト本文と検出件数を維持した。
- `performance` の次期4工程を定め、メンバー日別ドリルダウンの欠落context生成を `services/member_ajax.py` に復元して回帰テストを追加した。
- `performance` の履歴日別・履歴一覧・直近一覧AJAXのquery・表示row・context生成を `services/member_ajax.py` へ分離し、次期工程1を完了した。
- 活動中メンバーへの手動リマインド経路を削除し、自動リマインドのみを維持した。
- 個人の分析ページで「個人」と「全体」の指標カードをタブ切り替えに統合し、個人を初期表示にした。
- `performance` のメンバー実績transactionsを順序付きPrefetchで一括取得し、実績件数に比例するN+1がないことをクエリ数テストで固定した。
- 管理者ダッシュボードの「本日の活動状況」を、同格の白い状態パネル、上端アクセント、整理したメンバー実績カード、コンパクトな空状態へ再設計した。
- `performance` の過去入力メンバー候補APIを `services/adjustment_options.py` へ分離した。
- 補正画面のメンバー候補を全件先読みから選択部署だけの遅延取得へ変更し、次期改善4工程を完了した。
- `performance` の初期8工程・次期4工程とメール日次集計修正を含む13コミットを総合監査し、全379テストと公開前必須チェックの成功を確認した。
- 大きな工程では `project_manager` を開始時・終了時に必ず通し、範囲・完了条件・公開状態・次工程を更新する運用を明文化した。
- `performance` の有効メンバー一覧を、直近3稼働、3稼働連続0件、3稼働連続実績ありを第一視線で確認できる構造へ変更し、工程1の機械検証を完了した。
- 11アプリ、78テンプレート、URL、権限、CSS／JavaScript、NAV系統を監査し、`backend/docs/UI_SCREEN_INVENTORY.md` に全アプリUI・画面台帳を作成した。
- `dashboard` 管理トップと `performance` 管理トップに、目的別グループを持つ共通NAVを試験実装した。PCは左サイドNAV、スマホは同一HTMLのドロワーを使用し、現在位置、権限別管理項目、ログアウト分離、Escape、フォーカス循環、背景スクロール停止を実装した。
- 共通UIトークン、セクション、見出し、サマリー、一覧、タブ、フォーム、空・読み込み・エラー・完了状態を `ui_foundation.css` に定義し、利用規則を文書化した。
- 共通セクション見出しをテンプレート化し、`dashboard` と `performance` の管理トップへ共通UI基盤を試験適用した。
- 工程5の第1単位として、`dashboard` のメンバー一覧・登録編集・ID/PW一括管理・部署管理へ共通NAVとUI基盤を展開した。
- 工程5の第2単位として、`targets` の概要・月目標・路程目標へ共通NAV、画面内タブ、共通セクション基盤を展開した。
- 工程5の第3単位として、`mail` の統合設定・送信履歴へ共通NAV、画面内タブ、共通状態表示を展開した。
- Gmail連携の既存Client ID／Client Secret／Refresh TokenをHTMLへ再表示せず、空欄保存時は既存値を保持する契約を固定した。
- 工程5「管理・設定系」を完了し、`dashboard`、`targets`、`mail` の管理画面を共通UI基盤へ移行した。
- 工程6「日常入力系」を完了し、`reports` と `dairymetrics` の入力画面を共通NAV／UI基盤へ移行した。
- 工程7「閲覧・検索系」を完了し、`talks` と `testimony` の閲覧・検索・投稿管理画面を共通NAV／UI基盤へ移行した。
- 工程8「独立型アプリ」を完了し、`monthly_guide` と `mosaic` の固有表示・業務導線を維持しながら共通ヘッダーと操作規則を適用した。
- 工程9「認証・全体横断画面」を完了し、6つのログイン画面と403／404／500画面を共通規則へ統一した。
- 工程10「全体統合監査」を完了し、アプリURL 108件、全394テスト、権限・操作・状態・CSS／JavaScriptを横断確認した。
- 共通NAV移行後に未参照となった `talks` 専用ドロワーCSS／JavaScriptを削除した。
- `reports` の報告フォームに送信中表示と連続送信防止を追加し、入力と保存報告一覧を画面内タブで接続した。
- `dairymetrics` の決済入力に活動準備・決済入力・活動終了の段階表示を追加し、非同期差し替え後のフォームにも連続送信防止を適用した。

## 進行中の作業

- PUSH後、工程4までの画面を含む公開環境でPC／モバイルの視覚確認を行う。
- `performance` の監査済み14コミットはGitHubへのPUSHと公開環境確認が未完了。UI工程とは状態を分けて管理する。

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
- 大きな工程、複数ロール作業、公開準備では、`project_manager` が開始時に範囲と完了条件を固定し、終了時に公開可否、コミット/PUSH状態、次工程を更新する。
- 長期化、範囲超過、仕様判断待ち、原因不明のテスト失敗が発生した場合は `HANDOFF.md` を作成し、状態を `paused` にして統括へ返す。

## 未決事項

- 承認済み要件、設計書、タスク一覧、意思決定ログ、テスト結果をどのファイルへ集約するか。
- `PROJECT_STATE.md` の更新頻度を作業単位、PR単位、リリース単位のどれにするか。
- `dashboard/views.py` は818行まで縮小したが、部署管理の保存処理本体・メールテンプレート生成を別作業として追加分割する余地がある。
- `performance/views.py` は主要なsnapshot・明細・カード・メンバー個別context・補正query・候補queryをserviceへ分離済み。補正フォーム制御と過去入力のHTTPフローには追加分割の余地がある。
- 管理者ダッシュボードのメンバーカード集計はメンバー単位のN+1を避けているが、部署数には比例する。複数部署一括化は `final_actuals` の部署別一括APIを設計する別工程として扱う。

## ブロッカー

- 現在のChatGPT実行環境では外部Git書き込みが拒否されるため、監査済みブランチのGitHubへのPUSHは未完了。

## 工程4の終了判定

- 実装: 共通UIトークンと部品を独立CSSへ分離し、共通見出しテンプレートを追加した。
- 適用: `dashboard` と `performance` の管理トップが共通セクション、見出し、サマリー等を利用する。
- 状態: 空、読み込み、エラー、注意、完了の表示規則を用意した。
- 操作: キーボードフォーカス、モーション低減、モバイル向け2列／1列化を定義した。
- 検証: 対象82テスト、全380テスト、Django check、migration、BOM、JavaScript構文、差分検査が成功。npm lintは既存環境に `eslint` がないため起動不可。
- 残リスク: 作業環境からローカル画面へブラウザー接続できないため、実画面のPC／モバイル視覚確認は公開環境確認へ持ち越す。
- PUSH／公開: 未実施。

## 工程9の終了判定

- 実装: 6つのログイン画面へ共通フォーム・エラー・送信状態を適用し、403／404／500の復帰可能な専用画面を追加した。
- 操作: 既存認証、`next`、権限別遷移、各アプリのログアウト先、アプリ間入口を維持した。
- 検証: ログイン関連182テスト、工程対象18テスト、全394テスト、Django check、migration、BOM、差分検査が成功した。
- 残リスク: PC／モバイルの実画面視覚確認は工程10へ持ち越す。npm lintは既存環境に `eslint` がなく実行不可。
- PUSH／公開: 未実施。

## 工程10の終了判定

- 監査: 11アプリ、アプリURL 108件、権限、共通NAV、フォーム、AJAX、戻る操作、状態表示を横断確認した。
- 整理: 未参照の `talks` 専用ドロワーCSS／JavaScriptを削除した。稼働中CSSの一括統合はカスケード変更を避けるため行っていない。
- 検証: 全394テスト、Django check、migration、BOM、JavaScript構文、差分検査が成功した。npm lintは既存環境に `eslint` がなく実行不可。
- 判定: ローカル監査上はPUSH可能。公開環境のPC／モバイル主要導線確認を条件に公開完了とする。
- PUSH／公開: 未実施。

## 工程5の終了判定

- 実装: `dashboard`、`targets`、`mail` の管理・設定画面を共通NAV／UI基盤へ移行した。
- 操作: メール設定と送信履歴を画面内タブで接続し、メンバー候補更新失敗時も既存選択を維持する。
- 機密性: Gmailの既存Client ID／Client Secret／Refresh Tokenはレスポンスへ再表示しない。
- 検証: `mail` 対象19テスト、全384テスト、Django check、migration、BOM、差分検査が成功。npm lintは既存環境に `eslint` がないため起動不可。
- 残リスク: 作業環境からローカル画面へブラウザー接続できないため、PC／モバイル視覚確認は公開環境確認へ持ち越す。
- PUSH／公開: 未実施。

## 工程6の終了判定

- 実装: `reports` の一覧・入力・保存履歴と、`dairymetrics` の決済入力を共通NAV／UI基盤へ移行した。
- 操作: 報告入力・保存履歴をタブで接続し、決済入力は活動準備・決済入力・活動終了の段階を表示する。
- 送信状態: 通常保存フォームに連続送信防止、ボタン無効化、待機表示を追加し、既存のメール専用送信中・失敗表示を維持した。
- 検証: `reports` 対象31テスト、`dairymetrics` 対象53テスト、全388テスト、Django check、migration、BOM、差分検査が成功した。
- 残リスク: 作業環境からローカル画面へブラウザー接続できないため、PC／モバイル視覚確認は公開環境確認へ持ち越す。npm lintは既存環境に `eslint` がなく実行不可。
- PUSH／公開: 未実施。

## 工程8の終了判定

- 実装: `monthly_guide` は独立した長文比較レイアウトのまま共通ヘッダーを適用し、`mosaic` は専用業務NAVを共通シェルへ移行した。
- 操作: 言語変更・コピー結果を状態表示へ反映し、接客ログ・マスタ保存フォームに連続送信防止と待機表示を追加した。
- 権限: `mosaic` の一般メンバー向け導線、staff限定マスタ管理、専用ログアウトを維持した。
- 検証: 工程対象18テスト、全392テスト、Django check、migration、BOM、差分検査が成功した。
- 残リスク: PC／モバイルの実画面視覚確認は工程10へ持ち越す。npm lintは既存環境に `eslint` がなく実行不可。
- PUSH／公開: 未実施。

## 依存関係

- 開発工程ルールは `AGENTS.md` と `backend/docs/LOOP_ENGINEERING_GUIDE.md` を参照する。
- 作業ログは `backend/scripts/log_ai_work.py` を使う。

## 工程7の終了判定

- 実装: `talks` 6画面と `testimony` 共通ベースを共通NAV／アプリシェルへ移行した。
- 操作: 検索、タグ、未読、お気に入り、履歴、反応、編集・削除の既存処理と権限分岐を維持した。
- 検証: `talks` 対象34テスト、`testimony` 対象24テスト、全389テスト、Django check、migration、BOM、差分検査が成功した。
- 残リスク: PC／モバイルの実画面視覚確認は工程10へ持ち越す。npm lintは既存環境に `eslint` がなく実行不可。
- PUSH／公開: 未実施。

## 次に行う作業

- ユーザーの指示後、監査済みブランチをGitHubへPUSHする。
- デプロイ後、公開環境のPC／モバイル主要導線を確認して公開判定を確定する。

## 参照

- `AGENTS.md`
- `backend/docs/LOOP_ENGINEERING_GUIDE.md`
- `backend/docs/PERFORMANCE_RELEASE_AUDIT_2026-08-12.md`
- `backend/docs/UI_ROLLOUT_PLAN.md`
- `backend/docs/UI_SCREEN_INVENTORY.md`
- `logs/latest-summary.md`
