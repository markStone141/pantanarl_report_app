# 新UI全画面適用・完成監査

実施日: 2026-08-13

## 対象

- Django 11アプリのURL、権限分岐、共通シェル、独立UI、ログイン・ログアウト
- PCサイドNAV、モバイルドロワー、キーボード操作、戻る、AJAX、送信ロック
- 旧上部メニュー、旧ハンバーガークラス、固定インラインCSSの残存
- 全テスト、Django、migration、JavaScript、BOM、EOF、Git差分

## 横断監査結果

- URLパターン191件、名前付きURL178件をロードし、全405テストで認証、権限、保存、削除、検索、AJAX、戻る操作を確認した。
- 本番テンプレート86件を監査し、共通 `app-shell` ルート35件、明示的なドロワーボタン3系統を確認した。
- 3系統のドロワーボタンはすべて `ui-icon-button` を使用し、旧 `btn-inline dashboard-drawer-toggle` は0件だった。
- 到達不能になっていた旧 `topbar-menu-toggle`／`menu-collapsible` 生成コードとCSSを削除し、再混入防止テストを追加した。
- 残る `btn-inline` 57件は、ページング、コンパクトな編集・削除、固有画面の小型操作である。共通 `ui-button` との互換指定、または固有のサイズ指定として維持する。
- 共通ドロワーは通常リンクの明示遷移、Tab循環、Escape終了、背景スクロール停止を同じJavaScriptで提供する。
- 実績管理の部署選択はヘッダー内で、表示ボタンなしのAJAX切替、URL履歴、戻る操作、失敗時復元を維持する。

## 実ブラウザ確認

- ChromeのPC幅1440pxで、左サイドNAV、現在位置、ページヘッダー、本文シェルを確認した。
- Chromeのモバイル幅390pxで、ハンバーガー、開閉アイコン、背景遮蔽、ドロワー、現在位置、ログアウト導線を確認した。
- 確認には全migrationを適用した専用一時DBを使用し、既存のローカル業務データは変更対象にしなかった。
- 固定画像: `docs/ui-shell-desktop.png`、`docs/ui-shell-mobile.png`。

## 機械検証

- 全405テスト: 成功
- Django system check: 成功
- `makemigrations --check --dry-run`: 差分なし
- UIシェル監査スクリプト: 成功
- 管理対象JavaScript 13件の `node --check`: 成功
- BOM、EOF、`git diff --check`: 成功
- `npm run lint`: ローカルにeslintがないため未実行。JavaScript構文は上記13件を個別検査した。

## 完成判定と残リスク

ローカルの実装、自動テスト、静的監査、PC／モバイル実ブラウザ確認の範囲で、工程13の新UI全画面適用は完了と判定する。

PUSH、PR、デプロイは未実施。公開完了は、利用者による確認画像の承認と、公開環境での主要導線確認後に判定する。
