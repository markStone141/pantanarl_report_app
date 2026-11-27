# Pantanarl Report App

日次の活動実績を、メンバー入力から管理者確認、日報作成、分析、メール送信までつなぐ Django アプリです。

## 概要

このリポジトリは `backend/` を本体とする業務アプリです。主な用途は次の通りです。

- メンバーが当日の目標、決済明細、活動終了時の実績を入力する
- 管理者が部署別・メンバー別の実績、補正実績、ランキング、月次状況を確認する
- 報告担当者が部署別の日報を作成、修正、履歴確認する
- 決済獲得時のメールを Gmail API 経由で送信し、送信履歴を保存する
- 月目標、路程目標、期間別の分析を行う

UN / WV / Style 系の部署運用を想定しています。WV は CS と難民支援を分けて扱います。

## 主な画面

| パス | 用途 |
| --- | --- |
| `/performance/` | 実績管理の管理者向け画面 |
| `/performance/login/` | 実績管理ログイン |
| `/metrics/entry-v2-transaction/` | メンバー向け決済登録 |
| `/metrics/metrics-v2/` | Metrics V2 分析 |
| `/metrics/admin/` | 管理者向け日次概要 |
| `/reports/` | Report App の部署選択 |
| `/reports/history/` | 日報履歴 |
| `/targets/` | 目標管理 |
| `/mail/` | Gmail 連携・メールグループ設定 |
| `/talks/` | ナレッジ投稿 |
| `/testimony/` | 証言記事 |
| `/monthly_guide/` | 月次ガイド |

## アプリ構成

- `backend/config/`: Django 設定、URL、WSGI/ASGI
- `backend/apps/accounts/`: 部署、メンバー、ログイン連携
- `backend/apps/dairymetrics/`: 日次実績、決済登録、Metrics V2
- `backend/apps/performance/`: 管理者・メンバー実績画面
- `backend/apps/reports/`: 日報作成、履歴、修正
- `backend/apps/targets/`: 月目標、路程目標、指標目標
- `backend/apps/mail/`: Gmail 連携、送信先グループ、送信履歴
- `backend/apps/dashboard/`: 管理系ダッシュボード、メンバー設定
- `backend/apps/talks/`: ナレッジ投稿
- `backend/apps/testimony/`: 証言記事
- `backend/apps/monthly_guide/`: 月次ガイド
- `backend/docs/`: 運用マニュアル、管理者ガイド、報告者ガイド

## 決済メールの流れ

決済獲得時のメールは、`/metrics/entry-v2-transaction/` の決済登録画面から送信します。

1. 決済明細を登録する
2. 「登録してメール送信」または明細一覧の「メール送信」を押す
3. 件名・本文のプレビューが表示される
4. 必要に応じて本文を編集する
5. Gmail API で送信し、送信履歴を `MailSendHistory` に保存する

関連コード:

- `backend/apps/dairymetrics/views.py`: 決済登録、プレビュー表示、送信アクション
- `backend/apps/dairymetrics/services/entry_v2.py`: 決済メールの件名・本文テンプレート
- `backend/apps/mail/services.py`: Gmail API 送信、失敗記録、再送処理
- `backend/apps/mail/models.py`: Gmail 設定、送信先グループ、送信履歴
- `backend/apps/dairymetrics/templates/dairymetrics/entry_form_v2_transaction.html`: 決済登録画面とメールプレビュー

送信先は `MailDepartmentRouting` または `MailRecipientGroup` から部署ごとに解決されます。実送信では送信元アドレスを `To`、グループメンバーを `Cc` に入れます。

## ローカルセットアップ

Python 3.12 以上で `.venv` を作成してください。macOS 標準の Python 3.9 では Django 6 系をインストールできません。

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements/dev.txt
python manage.py migrate
python manage.py runserver
```

初期環境変数の例は `backend/.env.example` を参照してください。

## テスト

```bash
cd backend
source .venv/bin/activate
python manage.py test
```

変更範囲が限定される場合は、対象アプリのテストだけ実行します。

```bash
python manage.py test apps.dairymetrics.tests
python manage.py test apps.mail.tests
python manage.py test apps.reports.tests
```

## 補助チェック

ルートでは docs 用 JavaScript lint を実行できます。

```bash
npm run lint
```

編集後は BOM チェックも実行します。

```bash
cd backend
source .venv/bin/activate
python scripts/check_no_bom.py
```

## 本番運用・デプロイ

- 運用マニュアル: `backend/docs/OPERATION_MANUAL.md`
- 報告者ガイド: `backend/docs/REPORT_GUIDE.md`
- 管理者ガイド: `backend/docs/ADMIN_GUIDE.md`
- Cloud Run デプロイ: `backend/DEPLOY_CLOUD_RUN.md`

本番は Cloud Run と PostgreSQL を想定しています。通常運用ではマイグレーションを Cloud Run Job または GitHub Actions で実行します。
