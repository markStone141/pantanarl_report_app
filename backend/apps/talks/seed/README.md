# Talks Seed Manual

## 概要
このフォルダには、`talks` アプリの開発用データを投入するためのseedデータを置いています。

- seedファイル: `demo_data.json`
- 投入コマンド: `seed_talks_demo`
- 削除コマンド: `clear_talks_data`

## コマンド

### 1. データ投入
```bash
python manage.py seed_talks_demo
```

### 2. 既存データを削除してから再投入
```bash
python manage.py seed_talks_demo --reset
```

### 3. 別seedファイルを指定して投入
```bash
python manage.py seed_talks_demo --file your_seed.json
```

## データ削除

### 1. 投稿/コメント/ユーザー設定のみ削除（タグ/リアクションは残す）
```bash
python manage.py clear_talks_data --keep-master
```

### 2. talks関連データを全削除（タグ/リアクション含む）
```bash
python manage.py clear_talks_data
```

## 注意
- `--reset` や `clear_talks_data` は開発用のデータ操作です。
- 本番環境で実行する場合は十分に注意してください。
- `demo_data.json` の `author_name` は、既存 `Member` 名と一致すると自動で紐づきます。

## Supabase反映メモ（mainマージ時）
`Member.password` / `Member.login_id` 削除を含む変更を本番へ反映する際の手順メモです。

1. 本番DBバックアップを取得する  
   `supabase db dump`（または `pg_dump`）を先に実施。
2. アプリコードを `main` にマージし、デプロイ対象を確定する
3. migration適用順を事前確認する  
   `python manage.py migrate --plan`
4. 本番反映は同一リリース内で実施する  
   「コードデプロイ」→「`python manage.py migrate` 実行」
5. 反映後確認  
   - ログイン（Talks / Report）  
   - メンバー管理更新  
   - 投稿/コメント作成  
   - 管理者画面表示

補足:
- 今回の関連migration: `accounts 0007_remove_member_password` / `accounts 0008_remove_member_login_id`
- 本番に手動スキーマ変更がある場合は、`django_migrations` と実テーブル差分を先に確認してから実行すること。
