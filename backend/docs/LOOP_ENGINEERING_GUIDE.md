# ループエンジニアリング開発ガイド

AI作業は、以下のループで進める。目的は、ログを残すことだけではなく、開発そのものを「目的設定、情報収集、制約確認、実装、観測、検証、品質評価、修正、終了」の工程に分け、失敗時にどこで判断を誤ったか追跡できるようにすること。

## 開発プロセスとしての原則

- ロールは実際の別プロセスである必要はない。1人のAI作業でも、各ロールの観点を順番に通す。
- ログは証跡であり、開発工程の代替ではない。必ず実装前の計画、実装後の検証、意味的レビューを行う。
- 小さな作業でも、最低限 `planner -> implementer -> validator -> reviewer -> reporter` の観点を通す。
- UIを変更する作業では、`implementer` の後に必ず `ui_designer` の観点を通す。
- 大きな作業、DB変更、権限変更、UN/WV分岐、メール送信、デプロイ影響がある作業では、全ロールを明示的に通す。

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

作業工程は、以下のロールの観点に分けて進める。ログ上の区分だけではなく、開発判断そのものを分離する。

- `planner`: Goal / Context / Constraints / Plan を担当する。目的、影響範囲、制約、検証方針を決めてから実装へ渡す。
- `implementer`: Action を担当する。計画に沿ってコード、テンプレート、CSS、ドキュメントを変更する。勝手に制約を広げない。
- `observer`: Observe を担当する。コマンド結果、エラー、差分、画面上の変化を事実として整理する。解釈と事実を混ぜない。
- `validator`: Validate を担当する。テスト、Django check、migration check、BOM、diff check を実行する。失敗を握りつぶさない。
- `ui_designer`: UI/UX Review を担当する。情報設計、視線誘導、モバイル操作、余白、密度、既存CSS再利用、単調なカード量産の回避を評価する。
- `reviewer`: Review を担当する。仕様適合、権限、DBアクセス、N+1、部署分岐、UI品質、保守性を評価する。
- `repairer`: Repair を担当する。失敗やレビュー指摘を修正し、Observe / Validate / Review へ戻す。
- `reporter`: Stop を担当する。最終要約、残リスク、コミットID、未解決事項をまとめる。
- `agent`: 役割を明示しない小さな作業のデフォルト。

## 開発時チェックリスト

### Planner

- ユーザーの目的を1文で言えるか。
- 対象ファイル、対象画面、対象モデルを把握したか。
- 既存仕様と壊してはいけない挙動を確認したか。
- 必要な検証コマンドを決めたか。

### Implementer

- 計画外のファイルを触っていないか。
- 既存責務に沿って実装したか。
- 肥大化する場合にサービス、セレクタ、テンプレート分割を検討したか。
- 機密情報をログやコードに残していないか。

### Observer

- 実行結果、エラー、差分を確認したか。
- 失敗時に `logs/errors.json` へ記録したか。
- 推測ではなく出力に基づいて次の判断をしたか。

### Validator

- 対象テストを実行したか。
- `manage.py check` を実行したか。
- `makemigrations --check --dry-run` を実行したか。
- BOMチェックと `git diff --check` を実行したか。

### UI Designer

- ユーザーが最初に見るべき情報が上に来ているか。
- PCとモバイルで操作順序が自然か。
- カード、ボタン、バッジ、テーブルがワンパターンに増殖していないか。
- 余白、文字サイズ、コントラスト、密度が画面の用途に合っているか。
- 既存の共通CSSやデザイン変数を使い、場当たり的なインラインCSSを増やしていないか。
- 「表示できる」だけでなく、現場で疲れている状態でも使いやすいか。
- 変更前より情報の優先順位が明確になっているか。

### Reviewer

- ユーザーの依頼に対して意味的に合っているか。
- 権限、部署分岐、UN/WV混在、DB整合性に問題がないか。
- DBアクセス回数やN+1の懸念がないか。
- UI変更の場合、PC/モバイルの見え方に無理がないか。

## 構造化評価JSON

`validator`、`ui_designer`、`reviewer` が問題を検出した場合は、後続の `repairer` が迷わず修正できるように、可能な限り以下のJSON形式で評価結果を残す。

```json
{
  "result": "fail",
  "score": 72,
  "issues": [
    {
      "category": "technical_accuracy",
      "severity": "major",
      "location": "対象ファイルまたは画面上の位置",
      "problem": "何が問題かを事実ベースで書く",
      "required_fix": "どう直せば合格かを書く"
    }
  ],
  "retry_required": true
}
```

### フィールド

- `result`: `pass`、`fail`、`warning` のいずれか。
- `score`: 0から100の整数。厳密な採点が難しい場合も、後続判断の目安として付ける。
- `issues`: 問題の配列。問題がない場合は空配列。
- `retry_required`: 修正して再検証が必要なら `true`。

### issue.category

- `technical_accuracy`: 技術的説明、計算式、データ処理の誤り。
- `functional_correctness`: 仕様通りに動かない。
- `data_integrity`: DB整合性、マイグレーション、既存データ影響。
- `security_privacy`: 権限、機密情報、ログ、認証の問題。
- `performance`: N+1、DBアクセス過多、重い処理。
- `ui_ux`: 情報設計、操作性、モバイル表示、見た目の単調さ。
- `maintainability`: 責務分離、重複、肥大化、命名。
- `test_coverage`: テスト不足、検証不足。

### issue.severity

- `critical`: 本番障害、データ破損、機密漏えい、主要機能停止につながる。
- `major`: ユーザー影響が大きく、修正なしでは完了にできない。
- `minor`: 影響は限定的だが直すべき。
- `nit`: 品質改善レベル。

評価JSONは、人間向け説明の代替ではなく、修正工程への入力として扱う。最終報告では、重要な指摘だけを短く要約する。

### Repairer

- 失敗原因に対して最小修正で対応したか。
- 修正後に再検証したか。
- 同じ問題で3回以上止まる場合に人間へ引き渡したか。

### Reporter

- 変更内容を短く説明できるか。
- 実行した検証を明記したか。
- 残リスクや未実行テストがあれば明記したか。
- コミットIDを報告したか。

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
