# 利用マニュアル

このフォルダには、運用に必要な最小マニュアルをまとめています。

- `OPERATION_MANUAL.md`: 本番運用向け統合マニュアル
- `operation_manual_print.html`: PDF 配布用の印刷版
- `REPORT_GUIDE.md`: 報告者向け（報告入力・修正）
- `TARGET_GUIDE.md`: 目標管理向け（月目標・路程目標）
- `ADMIN_GUIDE.md`: 管理者向け（日次運用・メール本文作成）

## 推奨の読み順

1. 本番運用確認: `OPERATION_MANUAL.md`
2. 管理者: `ADMIN_GUIDE.md`
3. 報告者: `REPORT_GUIDE.md`
4. 目標設定担当: `TARGET_GUIDE.md`

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
