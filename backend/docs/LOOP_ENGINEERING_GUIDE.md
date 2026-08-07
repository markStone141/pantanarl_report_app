# ループエンジニアリング作業ガイド

AI作業は、以下のループで進める。目的は、作業内容を観測可能にし、失敗時にどこで判断を誤ったか追跡できるようにすること。

## 1. Goal: 目標

- ユーザーが求めている到達状態を1つに絞る。
- 成果物、対象画面、対象ファイル、完了条件を明確にする。
- 曖昧な場合は、合理的な仮定を置くか、リスクが高い場合だけ確認する。

推奨ログイベント: `goal_defined`

## 2. Context: 必要な情報

- 関連ファイル、既存ロジック、テスト、DBモデル、テンプレート、CSSを確認する。
- 推測だけで実装しない。
- 既存の仕様、過去の修正方針、ユーザーが明示した制約を拾う。

推奨ログイベント: `context_collected`

## 3. Constraints: 禁止事項・制約

- 触ってはいけないファイル、既存挙動、権限、機密情報、DB整合性、UI方針を明確にする。
- パスワード、APIキー、アクセストークン、Cookie、個人情報、環境変数全体はログに残さない。
- UN/WVなど分岐が必要な仕様は混ぜない。

推奨ログイベント: `constraints_identified`

## 4. Plan: 作業計画

- 変更単位を小さく分ける。
- 影響範囲、必要なテスト、ロールバックしやすい境界を決める。
- 大きな作業では、実装前にユーザーへ短く共有する。

推奨ログイベント: `plan_created`

## 5. Action: 実行

- 計画に従って実装する。
- 手作業の編集は `apply_patch` を使う。
- 既存の責務分離、共通CSS、サービス分割を崩さない。

推奨ログイベント: `action_completed`

## 6. Observe: 結果の取得

- コマンド出力、画面表示、差分、エラー、テスト失敗内容を確認する。
- 成功/失敗を事実として記録する。
- 失敗時は `logs/errors.json` に残す。

推奨ログイベント: `result_observed`

## 7. Validate: 機械的検査

- 対象テスト、`manage.py check`、`makemigrations --check --dry-run`、BOMチェック、`git diff --check` を実行する。
- フロントのみ、ドキュメントのみなどの場合も、可能な範囲で機械的検査を行う。

推奨ログイベント: `validation_completed`

## 8. Review: 意味・品質の評価

- テストが通るだけでなく、ユーザーの目的に合っているか確認する。
- DBアクセス、N+1、権限、部署分岐、モバイルUI、既存導線への影響を確認する。
- 不要な重複や肥大化がないか見る。

推奨ログイベント: `review_completed`

## 9. Repair: 修正

- 検査やレビューで問題があれば修正する。
- 修正後は再度 Observe / Validate / Review に戻る。
- 同じ問題で3回以上止まる場合は、人間へ引き渡す。

推奨ログイベント: `repair_completed`

## 10. Stop: 終了または人間へ引き渡し

- 完了条件を満たしたら、変更内容、検証結果、残リスク、コミットIDを短く報告する。
- 未解決リスクがある場合は、何が未解決かを明示する。
- コミット対象は作業目的に関係するファイルだけに限定する。

推奨ログイベント: `stopped`

## Agent Roles

作業工程は、ログ上で以下のロールに分けて記録できる。実際に複数プロセスで動かさない場合でも、どの観点で作業したかを後から追えるようにする。

- `planner`: Goal / Context / Constraints / Plan を担当する。目的、影響範囲、制約、検証方針を決める。
- `implementer`: Action を担当する。計画に沿ってコード、テンプレート、CSS、ドキュメントを変更する。
- `observer`: Observe を担当する。コマンド結果、エラー、差分、画面上の変化を事実として整理する。
- `validator`: Validate を担当する。テスト、Django check、migration check、BOM、diff check を実行する。
- `reviewer`: Review を担当する。仕様適合、権限、DBアクセス、N+1、部署分岐、UI品質を評価する。
- `repairer`: Repair を担当する。失敗やレビュー指摘を修正し、再検証へ戻す。
- `reporter`: Stop を担当する。最終要約、残リスク、コミットID、未解決事項をまとめる。
- `agent`: 役割を明示しない小さな作業のデフォルト。

ログ例:

```bash
cd backend
python3 scripts/log_ai_work.py \
  --run-id run-YYYYMMDD-HHMMSS \
  --loop 1 \
  --role planner \
  --event plan_created \
  --status success \
  --action "対象画面の修正計画を作成" \
  --reason "影響範囲と検証方法を明確化するため" \
  --next-action "implementer が実装に進む"
```

## ログ運用

- 通常イベントは `logs/execution.json` に記録する。
- 失敗、例外、ブロックは `logs/errors.json` に記録する。
- 機密情報を含む可能性があるログは、ユーザー確認後に `logs/sensitive.json` へ記録する。
- 直近作業の要約は `logs/latest-summary.md` に上書きする。

## 最小ログ例

```bash
cd backend
python3 scripts/log_ai_work.py \
  --run-id run-YYYYMMDD-HHMMSS \
  --loop 1 \
  --event goal_defined \
  --status success \
  --action "対象画面のUI崩れを修正する" \
  --reason "ユーザーがモバイル表示の崩れを報告したため" \
  --next-action "関連テンプレートとCSSを確認する"
```
