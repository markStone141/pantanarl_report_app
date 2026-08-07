# Project State

最終更新日: 2026-08-07

## 現在のフェーズ

- 開発運用整備

## プロジェクト全体の目標

- Report App、実績管理、決済入力、分析、通知、関連アプリを安全に保守・拡張できる状態にする。
- 仕様、設計、実装、テスト、監査、UI、運用判断をロールごとに分離し、作業の見落としを減らす。

## 完了した作業

- AI作業ログの標準ファイルを追加。
- 機密情報をログに残さない運用ルールを追加。
- ループエンジニアリング工程を文書化。
- ロール間Handoff JSONを文書化。
- `requirements_agent`、`test_designer`、`test_agent`、`test_auditor`、`ui_designer`、`project_manager`、`refactor_auditor` を追加。
- アプリ単位見直しの初回として `accounts` のログイン認証処理を service 層へ切り出し、対象テストを確認。
- `mail` のGmail API低レベル処理を専用モジュールへ分離し、既存送信サービスの互換性を対象テストで確認。

## 進行中の作業

- アプリ単位の構成、責務、依存、テスト見直し。次は `reports` / `targets` など小規模アプリから順に確認する。

## 確定事項

- 通常ログは `logs/execution.json`、エラーログは `logs/errors.json`、直近要約は `logs/latest-summary.md` に記録する。
- 機密情報を含む可能性があるログは通常ログに入れない。
- 要件が曖昧な場合は `requirements_agent` で整理してから計画へ進む。
- UI変更時は `ui_designer` の観点を通す。
- テスト設計、テスト実行・分類、テスト監査は別ロールとして扱う。
- リファクタリング監査は `refactor_auditor` として扱い、外部仕様変更と混在させない。
- 大規模な責務分離や構成変更は、承認なしに実装せず提案に留める。
- `project_manager` は、新機能完了、3ファイル以上の変更、類似処理追加、巨大ファイル化、新規フォルダや層の追加、既存コード依存の増加がある場合に `refactor_auditor` を呼ぶ。
- 長期化、範囲超過、仕様判断待ち、原因不明のテスト失敗が発生した場合は `HANDOFF.md` を作成し、状態を `paused` にして統括へ返す。

## 未決事項

- 承認済み要件、設計書、タスク一覧、意思決定ログ、テスト結果をどのファイルへ集約するか。
- `PROJECT_STATE.md` の更新頻度を作業単位、PR単位、リリース単位のどれにするか。

## ブロッカー

- なし。

## 依存関係

- 開発工程ルールは `AGENTS.md` と `backend/docs/LOOP_ENGINEERING_GUIDE.md` を参照する。
- 作業ログは `backend/scripts/log_ai_work.py` を使う。

## 次に行う作業

- 実際の機能開発時に `PROJECT_STATE.md` を更新し、運用しながら不足項目を調整する。

## 参照

- `AGENTS.md`
- `backend/docs/LOOP_ENGINEERING_GUIDE.md`
- `logs/latest-summary.md`
