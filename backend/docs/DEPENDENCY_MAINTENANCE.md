# 依存関係の更新・脆弱性対応

## 日常運用

- Dependabot: Python・GitHub Actions・Dockerを毎週月曜9:00（日本時間）、文書用npmを毎月確認する。通常更新PRはPython最大2件、他は各1件。minor/patch更新をまとめ、自動マージはしない。
- Dependency Security: 毎週月曜9:20（日本時間）にPythonの本番用依存関係をpip-auditで監査。ActionsのRun workflowから手動実行もできる。
- 脆弱性や実行障害は専用ワークフローの失敗で知らせる。ログ、監査JSON、解決した版の一覧を30日保存する。通常のデプロイとは独立しており、その実行を止めない。
- requirements・Dockerfile・ワークフローを変更するPRでは監査と回帰テストを実行する。既存Quality Checkも継続する。PRで本番の認証情報を使わない。

## マージ後にGitHub管理者が確認する設定

設定ファイルだけでは有効化できない項目がある。

1. Settings → Code security（または Code security and analysis）でDependency graph、Dependabot alerts、Dependabot security updatesを有効にする。
2. Security → Dependabotで検出結果を確認する。通常更新PRの上限はセキュリティ更新PRには適用されない。
3. 対応者はDependabot alertsとActions失敗通知を受け取るよう個人のGitHub通知設定を確認する。
4. 定期実行はデフォルトブランチへマージして初めて有効になる。Actions → Dependency Securityを一度手動実行する。
5. 定期監査をデプロイの依存ジョブや必須チェックにしない。既存のブランチ保護・リポジトリルールは維持する。

## 更新を求められたとき

1. CVE/GHSA、対象パッケージ、修正版、実際の利用箇所を確認する。外部から到達可能な機能に影響する重大な問題は優先し、通常更新は週次でまとめて確認する。
2. Actionsの失敗ログとartifactを読む。JSONがなければ通信・インストール等の障害を調べ、検出なしと混同しない。
3. Dependabot PRまたは作業ブランチで必要なバージョン範囲を更新する。間接依存なら親ライブラリの更新も確認する。警告の一律無視で済ませない。
4. 更新後の環境で検証する。

   ```bash
   cd backend
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements/dev.txt
   .venv/bin/python manage.py check
   .venv/bin/python manage.py test --noinput
   cd ..
   PATH="$PWD/backend/.venv/bin:$PATH" pre-commit run --all-files
   ```

   pre-commitは開発ツールとして別途インストールする。監査はActionsの手動実行で再確認する。
5. PRに影響範囲・更新前後の版・テスト結果・再監査結果を記載し、レビューする。自動マージはしない。
6. 通常のmainへのマージで既存Cloud Runデプロイが動く。反映後にログイン・実績入力・集計・メール本文プレビューを確認する。検証目的で通知メールを実送信しない。

## Python本体・Docker・本番稼働版

pip-auditの対象はPythonライブラリの既知の脆弱性。Python本体やDebian等のOSパッケージは対象外。

- Python公式のセキュリティ情報・サポート期限、ベースOSの情報も定期確認する。Docker更新PRだけで網羅できるわけではない。
- Dockerfileは`python:3.12-slim`。同じタグでも更新されるため、パッチ対応には新しいベースを取得して再ビルド・テスト・デプロイする。稼働中のCloud Runリビジョンは自動更新されない。
- Pythonのminor/major更新はDockerfileとCIの`python-version`を合わせ、Django対応版を確認し、そのPythonでテストする。現在のCIは3.12であり、Dockerだけ変更して成功しても新版Pythonの検証にはならない。
- requirementsは範囲指定でlockファイルではない。監査は実行時に新規解決した版を対象とし、本番の古いイメージの安全性は保証しない。CVE調査では対象リビジョンのイメージ・ビルド記録から実際の版も確認する。
- 本番イメージやOSの継続監査はArtifact Registryのイメージスキャンを別途検討する。課金・権限設定を伴うため今回は変更しない。

## 切り戻し

変更前のCloud Runリビジョンを控え、不具合時は既存手順でトラフィックを戻す。コードもrevert PRで整合させる。旧版に脆弱性がある場合は公開範囲の制限等も検討し、速やかに修正版へ戻す。DB変更を伴う更新はリビジョン切替だけではDBを復元できないため、事前に互換性とバックアップを確認する。
