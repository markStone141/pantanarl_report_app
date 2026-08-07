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
  --event validation_completed \
  --status success \
  --action "対象テストを実行" \
  --reason "変更箇所の回帰確認" \
  --next-action "差分チェック後にコミット"
```

失敗時は `--status fail` または `--status error` を使い、原因と次の対応を具体的に残す。

## 12. ループエンジニアリング工程

AI作業は以下の工程で進める。詳細は `backend/docs/LOOP_ENGINEERING_GUIDE.md` を参照する。

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

## 13. プロダクト方針メモ（実績入力・報告導線）

- Excel入力は将来的に廃止し、Webアプリ内で完結する入力導線を優先する
- 各メンバーにID/パスワードを配布し、`ログイン -> 当日の実績入力` までを最短導線で完了できるようにする
- 実績入力UIはモバイルファーストで設計し、疲れている状態でも入力しやすい軽さ・分かりやすさを優先する
- UI/UX は「義務感で入力する」より「つい開きたくなる」方向を目指し、軽快で少しわくわくする体験を重視する
- 代表者が最終的に報告する現在の運用は残す
- 代表者向け報告フォームには、メンバーが先に入力した当日実績が存在する場合、その内容を初期値として自動反映する
- 個人入力データから、平均・ランキング・進捗などの可視化を行い、振り返りとモチベーション向上につながる画面を優先する
- 実装判断で迷った場合は、`入力負荷の低減`、`モバイルの使いやすさ`、`報告忘れの防止` を優先する
