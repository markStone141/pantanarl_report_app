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
