# 利用マニュアル

このフォルダには、運用に必要な最小マニュアルをまとめています。

- `REPORT_GUIDE.md`: 報告者向け（報告入力・修正）
- `TARGET_GUIDE.md`: 目標管理向け（月目標・路程目標）
- `ADMIN_GUIDE.md`: 管理者向け（日次運用・メール本文作成）

## 推奨の読み順

1. 管理者: `ADMIN_GUIDE.md`
2. 報告者: `REPORT_GUIDE.md`
3. 目標設定担当: `TARGET_GUIDE.md`

## 開発ルール（文字化け防止）

1. 依存をインストール
   - `pip install pre-commit`
2. フックを有効化
   - `pre-commit install`
3. 事前チェックを実行
   - `pre-commit run --all-files`

上記で以下を自動チェックします。
- 改行コードの統一（LF）
- ファイル末尾改行
- Python構文エラー
- Django `manage.py check`
- UTF-8 BOM 混入
