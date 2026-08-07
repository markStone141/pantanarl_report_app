# AGENTS.md

このファイルは、このリポジトリで作業するエージェント向けの実行ルールです。

## 1. 作業ディレクトリ

- Djangoアプリ本体は `backend/`
- テスト・マイグレーション・開発サーバー操作は `backend/` で実行する

## 2. Python 環境セットアップ（必須）

テスト実行前に、以下が揃っていること:

1. `python3 -m venv backend/.venv`
2. `source backend/.venv/bin/activate`
3. `pip install -r backend/requirements/dev.txt`

`ModuleNotFoundError: No module named 'django'` が出た場合は、上記未実施が原因。

## 3. テスト実行の標準手順

### 全体テスト

```bash
cd backend
source .venv/bin/activate
python manage.py test
```

### 特定テストのみ

```bash
cd backend
source .venv/bin/activate
python manage.py test apps.dashboard.tests.DashboardTargetAndMailIntegrationTests
```

### 変更ファイル中心の最小確認

- `dashboard` 変更時: `apps.dashboard.tests`
- `reports` 変更時: `apps.reports.tests`
- `targets` 変更時: `apps.targets.tests`
- `testimony` 変更時: `apps.testimony.tests`
- `talks` 変更時: `apps.talks.tests`
- `accounts` 変更時: `apps.accounts.tests`

## 4. 補助チェック

### Docs JS の lint

```bash
npm run lint
```

実行場所はリポジトリルート（`package.json` がある場所）。

### BOMチェック（編集後に必須）

ファイル編集後は必ずBOMチェックを実施する。

```bash
cd backend
source .venv/bin/activate
python scripts/check_no_bom.py
```

### EOFチェック（編集後に必須）

ファイル編集後は、ファイル末尾に改行（LF）があることを確認する。

- pre-commit を使える場合:

```bash
pre-commit run --all-files
```

- もしくはGit差分で `\ No newline at end of file` が出ていないことを確認:

```bash
git diff
```

## 5. DB/マイグレーション

- ローカル確認では必要に応じて `python manage.py migrate` を実行
- モデル変更時は `python manage.py makemigrations` → `python manage.py migrate` → テスト

## 6. コミット時の注意

- 編集を行ったら、原則その作業ターン内でコミットまで実施する
- push は明示的に依頼された場合のみ実施する（デフォルトはコミットまで）
- 自動コミットを実施した場合は、コミット完了をコメントで必ず報告する
- ただし、コミット対象はその作業目的に関係するファイルに限定する
- 意図しない `backend/db.sqlite3` の変更は原則コミットしない
- 変更目的に関係ない差分はステージしない
- コミット前に、重複ロジック・不要な分岐・肥大化した処理など、リファクタリングできる箇所がないかを確認する
- 明らかに整理できる箇所がある場合は、関連差分の範囲で先にリファクタリングしてからコミットする

## 7. 実装方針（保守性）

- なるべく1ファイルの行数を増やしすぎない
- 追加実装で肥大化する場合は、`services/`, `selectors/`, `templates` の分割を優先する
- 複雑なロジックは既存ファイルへの追記より、責務単位で新規モジュールへ切り出す

## 8. フロント実装方針（CSS）

- なるべく共通CSSを優先して使う（まず既存クラスを探して再利用する）
- 色・余白・角丸・影など、共通化できる値はCSS変数（`--brand` など）を利用する
- 新しいクラスは必要最小限にし、同じ意味のクラスを増殖させない
- インラインCSSは原則避け、動的値が必要な箇所のみ最小限で使用する
- 複数テンプレートで同じ見た目が出る場合は、共通スタイルファイルへ寄せる
- 基本方針として、すべてのアプリのモバイル画面にはハンバーガーメニューとドロワーNAVを実装する（既存ロジックを再利用して統一する）

## 9. 新機能追加時の必須フロー

新しい機能を追加した場合、必ず以下を実施する:

1. 対応するテストを追加（または既存テストを拡張）
2. テストを実行
3. 失敗した場合は失敗ログを保存/記録

推奨ログ記録先:

- PR本文
- issueコメント
- 作業メモ（`docs/TODO.md` の不具合メモ欄など）

## 10. 失敗時の切り分け優先順

1. venvが有効か
2. `requirements/dev.txt` がインストール済みか
3. `backend/` でコマンドを打っているか
4. DBマイグレーションが必要な変更か

## 11. AI作業ログ

AI作業の透明性確保のため、作業ごとに `logs/` を更新する。

- `logs/execution.json`: 調査、実装、テスト、チェック、コミットなどの通常イベントを記録する
- `logs/errors.json`: テスト失敗、例外、未解決の問題、ブロック状態を記録する
- `logs/sensitive.json`: 機密情報を含む可能性があると明示確認されたイベントを記録する
- `logs/latest-summary.md`: 直近作業の人間向け要約を記録する

ログには以下を原則残さない。

- パスワード
- APIキー
- アクセストークン、リフレッシュトークン
- Cookie
- クレジットカード情報
- 個人情報の詳細
- 環境変数の全内容

これらがログに含まれる可能性がある場合は、保存前にユーザーへ確認する。通常は値をマスクし、必要な場合だけ `--sensitivity sensitive --allow-sensitive` を明示する。

保持期間は以下とする。

- 通常ログ: 30日
- エラーログ: 90日
- 実行サマリー: 1年間
- 機密情報を含む可能性があるログ: 7日

ログ追記は以下のスクリプトを優先する。

```bash
cd backend
python3 scripts/log_ai_work.py \
  --run-id run-YYYYMMDD-HHMMSS \
  --loop 1 \
  --role validator \
  --event validation_completed \
  --status success \
  --action "対象テストを実行" \
  --reason "変更箇所の回帰確認" \
  --next-action "差分チェック後にコミット"
```

失敗時は `--status fail` または `--status error` を使い、原因と次の対応を具体的に残す。

## 12. ループエンジニアリング開発工程

AI作業はログ記録だけでなく、開発プロセス自体を以下の工程で進める。詳細は `backend/docs/LOOP_ENGINEERING_GUIDE.md` を参照する。

1. Goal: 目標を明確にする
2. Context: 必要な情報を集める
3. Constraints: 禁止事項・制約を確認する
4. Plan: 作業計画を立てる
5. Action: 実行する
6. Observe: 結果を取得する
7. Validate: 機械的検査を行う
8. Review: 意味・品質を評価する
9. Repair: 必要なら修正して再検証する
10. Stop: 完了報告または人間へ引き渡す

各作業では、実際に複数人で分担していなくても、以下の担当観点を順番に通す。

- `project_manager`: プロジェクト全体の状態、依存関係、割り振り、完了条件を管理する
- `planner`: 実装前に目的、影響範囲、制約、検証方針を決める
- `requirements_agent`: 利用者の自然な要望を明確な要件へ変換する
- `implementer`: 計画に沿って変更する
- `observer`: 実行結果、差分、エラーを事実として確認する
- `validator`: 機械的チェックを実行する
- `test_designer`: 仕様と受け入れ条件を実行可能なテストへ変換する
- `test_agent`: 仕様と受け入れ条件に対するテスト検証を担当する
- `test_auditor`: テストが仕様に対して弱められていないか監査する
- `ui_designer`: UI変更時に情報設計、操作性、見た目の単調さを評価する
- `reviewer`: 仕様適合、権限、DBアクセス、UI品質、保守性を評価する
- `refactor_auditor`: 外部仕様を変えずに、重複、責務混在、依存関係、構成問題を監査する
- `repairer`: 問題があれば修正し、再度検証する
- `reporter`: 結果、残リスク、コミットIDをまとめる

小さな作業でも、最低限 `planner -> implementer -> validator -> reviewer -> reporter` の観点を通す。
UIを変更する作業では、`implementer` の後に必ず `ui_designer` の観点を通す。
`project_manager` は、新機能完了、3ファイル以上の変更、類似処理追加、巨大ファイル化、新規フォルダや層の追加、既存コード依存の増加がある場合、`refactor_auditor` の観点を呼び出す。
作業が長期化し、同じ問題への試行が3回を超える、変更ファイルが10件を超える、変更行数が500行を超える、仕様判断が必要になる、当初範囲を超える、テスト失敗原因が特定できない、新しい設計変更が必要になる場合は、無理に継続しない。`HANDOFF.md` を作成し、`PROJECT_STATE.md` の状態を `paused` に更新して、統括へ返す。

ログイベント名は原則として以下に揃える。

- `goal_defined`
- `context_collected`
- `constraints_identified`
- `plan_created`
- `action_completed`
- `result_observed`
- `validation_completed`
- `review_completed`
- `repair_completed`
- `stopped`

ログの `role` は、上記の開発担当観点に合わせて以下に揃える。

- `project_manager`: Project Coordination を担当する
- `planner`: Goal / Context / Constraints / Plan を担当する
- `requirements_agent`: Requirements Analysis を担当する
- `implementer`: Action を担当する
- `observer`: Observe を担当する
- `validator`: Validate を担当する
- `test_designer`: Test Design / Test Implementation を担当する
- `test_agent`: Test Review を担当する
- `test_auditor`: Test Audit を担当する
- `ui_designer`: UI/UX Review を担当する
- `reviewer`: Review を担当する
- `refactor_auditor`: Refactoring / Architecture Audit を担当する
- `repairer`: Repair を担当する
- `reporter`: Stop と最終報告を担当する
- `agent`: 小さな作業や役割分離しない作業のデフォルト

評価担当ロール（`validator`、`test_agent`、`test_auditor`、`ui_designer`、`reviewer`、`refactor_auditor`）が問題を検出した場合は、可能な限り構造化JSONで評価結果を残す。形式は `backend/docs/LOOP_ENGINEERING_GUIDE.md` の「構造化評価JSON」を標準とする。
ロール間の受け渡しは、必要に応じて構造化JSONで残す。形式は `backend/docs/LOOP_ENGINEERING_GUIDE.md` の「ロール間Handoff JSON」を標準とする。
プロジェクト全体の現在地は `PROJECT_STATE.md` に残す。大きな作業、複数ロールにまたがる作業、未決事項や依存関係が増えた作業では、作業後に `PROJECT_STATE.md` を更新する。

## 13. プロダクト方針メモ（実績入力・報告導線）

- Excel入力は将来的に廃止し、Webアプリ内で完結する入力導線を優先する
- 各メンバーにID/パスワードを配布し、`ログイン -> 当日の実績入力` までを最短導線で完了できるようにする
- 実績入力UIはモバイルファーストで設計し、疲れている状態でも入力しやすい軽さ・分かりやすさを優先する
- UI/UX は「義務感で入力する」より「つい開きたくなる」方向を目指し、軽快で少しわくわくする体験を重視する
- 代表者が最終的に報告する現在の運用は残す
- 代表者向け報告フォームには、メンバーが先に入力した当日実績が存在する場合、その内容を初期値として自動反映する
- 個人入力データから、平均・ランキング・進捗などの可視化を行い、振り返りとモチベーション向上につながる画面を優先する
- 実装判断で迷った場合は、`入力負荷の低減`、`モバイルの使いやすさ`、`報告忘れの防止` を優先する
