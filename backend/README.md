# Backend

Pantanarl Report App の Django 本体です。日次実績、決済登録、日報、目標管理、分析、メール送信を扱います。

## 構成

- `config/settings/base.py`, `local.py`, `prod.py`: Django 設定
- `config/urls.py`: 各アプリの URL 入口
- `apps/accounts/`: 部署、メンバー、ユーザー連携
- `apps/dairymetrics/`: 日次実績、決済登録、Metrics V2
- `apps/performance/`: 実績管理画面
- `apps/reports/`: 日報作成、履歴、編集
- `apps/targets/`: 月目標、路程目標、指標目標
- `apps/mail/`: Gmail 連携、送信先グループ、送信履歴
- `apps/dashboard/`: 管理ダッシュボード、メンバー設定
- `apps/talks/`: ナレッジ投稿
- `apps/testimony/`: 証言記事
- `apps/monthly_guide/`: 月次ガイド
- `docs/`: 運用マニュアル類

## 決済メール

決済登録画面は `/metrics/entry-v2-transaction/` です。

主な流れ:

1. `apps/dairymetrics/views.py` の `entry_form_v2_transaction_demo` で決済明細を保存する
2. `apps/dairymetrics/services/entry_v2.py` の `build_transaction_mail_preview` で件名・本文を作る
3. 画面上のプレビューモーダルで件名・本文を編集できる
4. `apps/mail/services.py` の `send_transaction_mail` が Gmail API で送信する
5. 送信成功・失敗・再送状態は `apps/mail/models.py` の `MailSendHistory` に保存する

送信先グループは `MailDepartmentRouting` を優先し、なければ部署に紐づく `MailRecipientGroup` から解決します。

## ローカル起動

Python 3.12 以上で `.venv` を作成してください。macOS 標準の Python 3.9 では Django 6 系をインストールできません。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements/dev.txt
python manage.py migrate
python manage.py runserver
```

## 環境変数

ローカルの例は `.env.example` を参照してください。

主な項目:

- `DJANGO_SETTINGS_MODULE`
- `SECRET_KEY`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `DB_ENGINE`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`
- `DB_PORT`

## テスト

```bash
source .venv/bin/activate
python manage.py test
```

対象アプリだけ確認する例:

```bash
python manage.py test apps.dairymetrics.tests
python manage.py test apps.mail.tests
python manage.py test apps.reports.tests
```

## デプロイ

Cloud Run へのデプロイ手順は `DEPLOY_CLOUD_RUN.md` を参照してください。
