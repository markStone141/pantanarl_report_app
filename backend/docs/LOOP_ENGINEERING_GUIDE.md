# ループエンジニアリング開発ガイド

AI作業は、以下のループで進める。目的は、ログを残すことだけではなく、開発そのものを「目的設定、情報収集、制約確認、実装、観測、検証、品質評価、修正、終了」の工程に分け、失敗時にどこで判断を誤ったか追跡できるようにすること。

## 開発プロセスとしての原則

- ロールは実際の別プロセスである必要はない。1人のAI作業でも、各ロールの観点を順番に通す。
- ログは証跡であり、開発工程の代替ではない。必ず実装前の計画、実装後の検証、意味的レビューを行う。
- プロジェクト全体の現在地は `PROJECT_STATE.md` を正とし、会話履歴だけで判断しない。
- 小さな作業でも、最低限 `planner -> implementer -> validator -> reviewer -> reporter` の観点を通す。
- 要望が曖昧、業務ルールが絡む、権限やデータ扱いが重要な作業では、`planner` の前に `requirements_agent` の観点を通す。
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

- `project_manager`: Project Coordination を担当する。プロジェクト全体の目標、現在地、確定事項、未決事項、進捗、依存関係を管理し、適切な専門ロールへ作業を割り振る。
- `planner`: Goal / Context / Constraints / Plan を担当する。目的、影響範囲、制約、検証方針を決めてから実装へ渡す。
- `requirements_agent`: Requirements Analysis を担当する。利用者の自然な要望を、設計、実装、テスト可能な明確な要件へ変換する。実装コードは書かず、技術を先に決めつけない。
- `implementer`: Action を担当する。計画に沿ってコード、テンプレート、CSS、ドキュメントを変更する。勝手に制約を広げない。
- `observer`: Observe を担当する。コマンド結果、エラー、差分、画面上の変化を事実として整理する。解釈と事実を混ぜない。
- `validator`: Validate を担当する。テスト、Django check、migration check、BOM、diff check を実行する。失敗を握りつぶさない。
- `test_designer`: Test Design / Test Implementation を担当する。仕様と受け入れ条件を実行可能なテストへ変換する。本番コードは変更しない。
- `test_agent`: Test Review を担当する。仕様と受け入れ条件に対する検証、失敗分類、再現可能な証拠の記録を行う。本番コードは変更しない。
- `test_auditor`: Test Audit を担当する。作成されたテストが実装に都合よく弱められていないか監査する。本番コードとテストコードは直接変更しない。
- `ui_designer`: UI/UX Review を担当する。情報設計、視線誘導、モバイル操作、余白、密度、既存CSS再利用、単調なカード量産の回避を評価する。
- `reviewer`: Review を担当する。仕様適合、権限、DBアクセス、N+1、部署分岐、UI品質、保守性を評価する。
- `repairer`: Repair を担当する。失敗やレビュー指摘を修正し、Observe / Validate / Review へ戻す。
- `reporter`: Stop を担当する。最終要約、残リスク、コミットID、未解決事項をまとめる。
- `agent`: 役割を明示しない小さな作業のデフォルト。

## 開発時チェックリスト

### Project Manager

目的は、プロジェクト全体の目標、現在地、確定事項、未決事項、進捗、依存関係を管理し、適切な専門ロールへ作業を割り振ること。

主な責任:

1. ユーザーの要望を既存仕様と照合する
2. 新規要件、変更要件、不具合を分類する
3. 曖昧な要件は `requirements_agent` へ渡す
4. 技術判断は `planner` または設計担当へ渡す
5. 実装は `implementer` へ渡す
6. テスト作成、レビュー、実行を適切なテスト系ロールへ依頼する
7. 各成果物の整合性を確認する
8. 未解決事項とブロッカーを管理する
9. 完了条件を満たしたか確認する
10. `PROJECT_STATE.md` を更新する

必ず参照するもの:

- `PROJECT_STATE.md`
- 承認済み要件
- 現在の設計書
- タスク一覧
- 意思決定ログ
- テスト結果

禁止:

- 未確定事項を勝手に確定しない
- 専門ロールの成果物を無条件で承認しない
- テスト未実施の機能を完了扱いにしない
- 現在の状態を会話履歴だけで判断しない
- 依存関係を無視して作業を開始しない

各作業後に更新するもの:

- 現在のフェーズ
- 完了した作業
- 進行中の作業
- ブロッカー
- 新たに確定した事項
- 新たな未決事項
- 次に行う作業

### Requirements Agent

目的は、利用者の自然な要望を、設計、実装、テストが可能な明確な要件へ変換すること。実装コードは書かない。技術を先に決めつけない。不足情報を黙って補完しない。

最初に整理する項目:

1. 利用者が解決したい問題
2. この機能を使う人物
3. 利用する場面
4. 実現したい結果
5. 業務上のルール
6. 権限とデータの扱い
7. 曖昧な表現
8. 不足している情報
9. 要望同士の矛盾
10. 今回の対象範囲

不足事項は以下に分類する:

- 実装前に必ず確認が必要
- 仮定を明示すれば進行可能
- 今回の対象外にできる

出力には以下を含める:

- 目的
- 利用者
- ユーザーストーリー
- 機能要件
- 非機能要件
- 受け入れ条件
- 業務ルール
- 権限
- 仮定
- 未決事項
- 対象外
- 開発担当への引き継ぎ事項

曖昧な表現は、観察またはテスト可能な条件へ変換する。

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

### Test Designer

目的は、仕様と受け入れ条件を実行可能なテストへ変換すること。既存実装の現在の挙動を正解として扱わず、仕様に基づいて期待値を定義する。

参照優先順位:

1. 受け入れ条件
2. 仕様書
3. API契約
4. 承認済みテスト設計
5. 実装コード

許可:

- 仕様書の読み取り
- 本番コードの読み取り
- `tests` ディレクトリへの書き込み
- テストの試験実行

禁止:

- 本番コードの変更
- 仕様に存在しない期待値の追加
- 実装の現在の挙動を正解として扱う
- 失敗するテストの削除
- `skip` による回避
- 対象処理全体をモックに置き換える

テスト設計時は、正常系、異常系、境界値、権限、重複処理、外部依存の失敗、回帰のうち、対象仕様に関係する観点を明示する。テスト追加後に失敗した場合でも、仕様に合っているなら期待値を実装結果へ合わせない。

### Test Agent

目的は、実装が仕様と受け入れ条件を満たすかを検証し、再現可能な証拠を添えて問題を報告すること。成功条件はテストをすべて緑にすることではなく、実装上の問題、テスト上の問題、仕様の曖昧さを正確に分類すること。

参照優先順位:

1. 受け入れ条件
2. 仕様書
3. API契約
4. 承認済みの既存テスト
5. 実装コード

許可:

- ソースコードの読み取り
- `tests` ディレクトリ内の変更
- テストコマンドの実行
- テスト結果の記録

禁止:

- 本番コードの変更
- 仕様の変更
- 失敗するテストの削除や無効化
- 期待値を実装結果へ安易に合わせる
- 本番環境や本番データへのアクセス

テスト観点:

- 正常系
- 異常系
- 境界値
- 権限
- 重複処理
- 外部依存の失敗
- 回帰

失敗時は、`PRODUCT_BUG`、`TEST_BUG`、`SPEC_AMBIGUITY`、`ENVIRONMENT_ERROR`、`FLAKY_TEST`、`UNKNOWN` のいずれかに分類する。同じ問題への再試行は最大2回。実装上の不具合と判断した場合は、テストを変更せず開発担当へ返す。

各報告には、実行コマンド、期待結果、実際の結果、再現手順、根拠、変更したテストファイル、本番コードを変更していないことを含める。

### Test Auditor

目的は、作成されたテストが実装に都合のよい内容へ弱められていないか監査すること。成功条件はテストを通すことではなく、不足、誤り、弱い検証、不正な回避を発見すること。

参照優先順位:

1. 受け入れ条件
2. 仕様書
3. API契約
4. テスト設計書
5. テストコード
6. 実装コード

確認項目:

1. 各要件に対応するテストがあるか
2. 正常系、異常系、境界値があるか
3. 期待値が仕様に基づいているか
4. assertが具体的か
5. 重要な副作用を確認しているか
6. モックで対象処理を回避していないか
7. テストが単独で実行可能か
8. 時刻、乱数、実行順序に依存していないか
9. `skip`、削除、期待値変更による回避がないか
10. 実装を意図的に壊した場合に失敗するか

禁止:

- 本番コードを変更しない
- テストコードを直接修正しない
- 仕様を推測で補完しない
- テスト成功を理由に合格としない

出力には、合格または不合格、重大度、対象テスト、問題点、見逃す可能性のある不具合、仕様上の根拠、必要な修正を含める。

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

`validator`、`test_agent`、`test_auditor`、`ui_designer`、`reviewer` が問題を検出した場合は、後続の `repairer` が迷わず修正できるように、可能な限り以下のJSON形式で評価結果を残す。

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

### test_agent.failure_type

`test_agent` が失敗を報告する場合は、`issues` の各要素に `failure_type` を追加する。

- `PRODUCT_BUG`: 実装上の不具合。
- `TEST_BUG`: テスト自体の誤り。
- `SPEC_AMBIGUITY`: 仕様や受け入れ条件が曖昧。
- `ENVIRONMENT_ERROR`: 環境、依存、設定による失敗。
- `FLAKY_TEST`: 再現性が不安定な失敗。
- `UNKNOWN`: 原因分類がまだできない失敗。

`test_agent` の報告例:

```json
{
  "result": "fail",
  "score": 64,
  "issues": [
    {
      "category": "functional_correctness",
      "severity": "major",
      "failure_type": "PRODUCT_BUG",
      "location": "apps.example.tests.ExampleFlowTests.test_duplicate_submit",
      "problem": "重複送信時に既存エントリーへ紐づかず、同一内容のレコードが追加される",
      "required_fix": "同一メンバー、同一日付、同一決済内容の場合は重複登録せず既存エントリーを再利用する"
    }
  ],
  "retry_required": true,
  "evidence": {
    "command": "./.venv/bin/python manage.py test apps.example.tests.ExampleFlowTests",
    "expected": "重複登録されず既存エントリーが利用される",
    "actual": "同一内容のレコードが2件作成された",
    "reproduction_steps": ["対象テストを実行する", "DB上の作成件数を確認する"],
    "test_files_changed": ["apps/example/tests.py"],
    "production_code_changed": false
  }
}
```

### test_auditor.audit_result

`test_auditor` が監査する場合は、以下のJSON形式で監査結果を残す。

```json
{
  "result": "fail",
  "severity": "major",
  "target_tests": ["apps.example.tests.ExampleFlowTests.test_duplicate_submit"],
  "issues": [
    {
      "category": "test_coverage",
      "severity": "major",
      "location": "apps/example/tests.py",
      "problem": "重複送信時のDB副作用をassertしておらず、レスポンス成功だけを確認している",
      "missed_bug_risk": "同一内容のレコードが重複作成されてもテストが通る",
      "spec_basis": "同一決済内容は重複登録しないという受け入れ条件",
      "required_fix": "登録件数と既存エントリー再利用を具体的にassertする"
    }
  ],
  "retry_required": true
}
```

### issue.severity

- `critical`: 本番障害、データ破損、機密漏えい、主要機能停止につながる。
- `major`: ユーザー影響が大きく、修正なしでは完了にできない。
- `minor`: 影響は限定的だが直すべき。
- `nit`: 品質改善レベル。

評価JSONは、人間向け説明の代替ではなく、修正工程への入力として扱う。最終報告では、重要な指摘だけを短く要約する。

## ロール間Handoff JSON

ロール間の受け渡しは、必要に応じて以下のJSON形式で残す。目的は、前工程の判断、制約、成果、未解決事項を後続ロールが誤解しないようにすること。

```json
{
  "handoff_id": "handoff-run-YYYYMMDD-HHMMSS-001",
  "run_id": "run-YYYYMMDD-HHMMSS",
  "from_role": "planner",
  "to_role": "implementer",
  "status": "ready",
  "summary": "対象画面のUI崩れを修正する",
  "inputs": {
    "user_goal": "ユーザーが求めている到達状態",
    "context": ["確認済みファイルや既存仕様"],
    "constraints": ["触ってはいけない挙動や注意点"]
  },
  "outputs": {
    "decisions": ["前工程で決めたこと"],
    "changed_files": [],
    "commands_run": [],
    "validation": null
  },
  "open_questions": [],
  "risks": [],
  "next_actions": ["次のロールが最初にやること"]
}
```

### handoff.status

- `ready`: 次のロールへ進める。
- `blocked`: 人間の判断や外部状態が必要。
- `needs_repair`: 修正工程へ戻す必要がある。
- `complete`: 最終報告へ進める。

### 運用ルール

- `project_manager -> requirements_agent`: 曖昧な要望、業務ルール、権限、未決事項の整理を依頼する。
- `project_manager -> planner`: 確定済み要件、依存関係、対象範囲、完了条件を渡す。
- `requirements_agent -> planner`: 目的、利用者、受け入れ条件、業務ルール、権限、未決事項、対象外を渡す。
- `planner -> implementer`: 目的、影響範囲、制約、検証方針を渡す。
- `implementer -> observer`: 変更内容、変更ファイル、実行した操作を渡す。
- `observer -> validator`: 実行結果、エラー、再現条件を渡す。
- `validator -> reviewer`: テスト結果、未実行チェック、機械的な懸念を渡す。
- `test_designer -> test_agent`: 追加したテスト、参照した仕様、期待値の根拠、試験実行結果を渡す。
- `test_agent -> reviewer`: テスト観点、失敗分類、再現手順、変更したテストファイルを渡す。
- `test_auditor -> test_designer`: 弱い検証、不足ケース、不正な回避、必要なテスト修正を渡す。
- `ui_designer -> reviewer`: UI評価、PC/モバイルの懸念、改善案を渡す。
- `reviewer -> repairer`: 構造化評価JSONと修正優先度を渡す。
- `repairer -> validator`: 修正内容と再検証すべき項目を渡す。
- `reporter -> human`: 変更内容、検証結果、残リスク、コミットIDをMarkdownで要約する。

Handoff JSONには、パスワード、APIキー、アクセストークン、Cookie、個人情報、環境変数全体を含めない。含む可能性がある場合は、通常ログではなくユーザー確認後に `logs/sensitive.json` へ分離する。

## 要件整理JSON

`requirements_agent` は、必要に応じて以下のJSON形式で要件を整理する。

```json
{
  "purpose": "この機能で解決したい問題",
  "users": ["この機能を使う人物"],
  "user_stories": [
    "利用者として、目的のために、何ができるようになりたい"
  ],
  "functional_requirements": [
    "観察またはテスト可能な機能要件"
  ],
  "non_functional_requirements": [
    "性能、操作性、監査性、保守性など"
  ],
  "acceptance_criteria": [
    "Given/When/Then または同等に検証可能な条件"
  ],
  "business_rules": [
    "業務上守る必要があるルール"
  ],
  "permissions": [
    "誰が何を閲覧、作成、変更、削除できるか"
  ],
  "data_handling": [
    "保存、表示、削除、ログ、個人情報の扱い"
  ],
  "assumptions": [
    "仮定を明示すれば進行可能な事項"
  ],
  "open_questions": {
    "must_confirm_before_implementation": [],
    "can_proceed_with_assumption": [],
    "out_of_scope_this_time": []
  },
  "conflicts": [
    "要望同士の矛盾"
  ],
  "out_of_scope": [
    "今回やらないこと"
  ],
  "handoff_to_development": [
    "開発担当が最初に確認、設計、実装すべきこと"
  ]
}
```

要件整理JSONは、実装指示そのものではなく、`planner` が計画を作るための入力として扱う。技術選定、DB設計、UI詳細は、要件から必要性が確認できた後に決める。

## プロジェクト状態管理

`project_manager` は、プロジェクト全体の現在地を `PROJECT_STATE.md` に記録する。会話履歴だけを根拠に状態判断をしない。

`PROJECT_STATE.md` には最低限以下を含める。

- 現在のフェーズ
- プロジェクト全体の目標
- 完了した作業
- 進行中の作業
- 確定事項
- 未決事項
- ブロッカー
- 依存関係
- 次に行う作業
- 参照すべき要件、設計、タスク、意思決定、テスト結果
- 最終更新日時

状態更新時は、未確定事項を確定済みに移動しない。専門ロールの成果物は、受け入れ条件、設計、テスト結果と照合してから完了扱いにする。

プロジェクト状態をJSONで渡す場合の形式:

```json
{
  "phase": "requirements | design | implementation | testing | release_preparation | maintenance",
  "goals": [],
  "completed_work": [],
  "in_progress": [],
  "confirmed_decisions": [],
  "open_questions": [],
  "blockers": [],
  "dependencies": [],
  "next_actions": [],
  "references": {
    "requirements": [],
    "design_docs": [],
    "tasks": [],
    "decision_log": [],
    "test_results": []
  },
  "last_updated": "YYYY-MM-DD"
}
```

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
