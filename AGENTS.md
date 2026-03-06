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
