# 共通UI基盤

最終更新日: 2026-08-12

## 目的

各アプリ固有の情報設計を維持しながら、色、余白、見出し、カード、フォーム、タブ、ボタン、画面状態の意味と操作感を統一する。新規画面は `static/ui_foundation.css` を優先し、既存の同義クラスを増やさない。

## 読み込み

`base.html` が `app.css` の後に `ui_foundation.css` を読み込む。既存画面への適用は工程単位で行い、一斉置換しない。

## 基本トークン

| 種別 | 変数 | 用途 |
|---|---|---|
| 面 | `--ui-surface*` | ページ、カード、補助面 |
| 文字 | `--ui-text*` | 本文、補助文字 |
| 境界 | `--ui-border*` | カード、区切り、入力欄 |
| 状態 | `--ui-success*` / `--ui-warning*` / `--ui-danger*` | 完了、注意、エラー |
| 余白 | `--ui-space-1`〜`--ui-space-6` | 4px単位の余白階層 |
| 角丸 | `--ui-radius-sm`〜`--ui-radius-lg` | 入力、内側カード、セクション |
| フォーカス | `--ui-focus` | キーボード操作時の共通リング |

## 共通部品

| 部品 | クラス／テンプレート | 規則 |
|---|---|---|
| セクション | `.ui-section` | 画面内の大きな情報単位に使う |
| 見出し | `includes/ui_section_heading.html` | kicker、見出し、説明、右側補助情報を同じ順序にする |
| サマリー | `.ui-summary-grid`, `.ui-summary-card` | 主要数値の比較に使い、詳細本文には使わない |
| 一覧カード | `.ui-list-card` | 表よりカードが適切な小規模一覧に使う |
| タブ | `.ui-tabs`, `.ui-tab` | 選択状態を `aria-selected` または `.is-active` でも示す |
| フォーム | `.ui-form-grid`, `.ui-field`, `.ui-field-help` | ラベルを入力欄の前に置き、説明とエラー位置を固定する |
| 空状態 | `.ui-state` | 「何もない理由」と必要なら次の操作を示す |
| 読み込み | `.ui-state.ui-state--loading` | 通信開始前に表示し、完了・失敗時に必ず解除する |
| 結果通知 | `.ui-feedback--success/warning/error` | 保存結果など画面全体に関わる状態に使う |
| 主要操作 | `.ui-button.ui-button--primary` | 保存、登録、送信など、操作群で最も重要な1操作に使う |
| 通常操作 | `.ui-button.ui-button--secondary` | 編集、詳細、追加読み込みなどに使う |
| 補助操作 | `.ui-button.ui-button--quiet` | キャンセル、閉じる、リセットなどに使う |
| 危険操作 | `.ui-button.ui-button--danger` | 削除、無効化、活動終了などに使う |
| アイコン操作 | `.ui-icon-button` | `aria-label` と `title` を付け、危険操作は `--danger` を併用する |
| 選択操作 | `.ui-choice-button` | 表示切替、フィルタ、タブに使い、選択状態を属性と文字でも示す |

## ボタン規則

- 主要操作をNAVと同じ濃紺で表し、画面または操作群につき原則1つに絞る。
- `hover`、`focus-visible`、`active`、`disabled`、`.is-loading` を共通定義で扱う。
- `.is-loading` では `aria-busy="true"` と処理中の文言を併用し、二重送信防止ロジックは画面側で維持する。
- `Choice` の選択中は `.is-active` だけでなく `aria-pressed`、`aria-selected` または `aria-current` を付ける。
- 静的な確認画面は `docs/button-ui-preview.html`。Django、DB、ログインなしで直接確認できる。

## アクセシビリティとモバイル

- 操作要素は `:focus-visible` で共通フォーカスを表示する。
- 色だけで状態を伝えず、見出しまたは本文を併記する。
- 読み込みアニメーションは `prefers-reduced-motion` で停止する。
- 768px以下ではセクション余白を縮小し、サマリーは2列、フォームは1列にする。480px以下ではサマリーも1列にする。
- タブは項目を折り返さず横方向へ退避できるが、主要本文には横スクロールを使わない。

## 適用状況

- `dashboard` 管理トップ: セクション、共通見出し、サマリー。
- `dashboard` 管理トップ: Primary、Secondary、Quiet、Choiceを試験適用。
- `performance` 補正実績: Primary、Secondary、Quiet、Icon、Dangerを試験適用。
- 共通NAV: `includes/app_navigation.html` と `dashboard/mobile_drawer.css` を引き続き使用する。

工程5以降は、対象アプリごとに既存クラスとの競合を確認してから、この基盤へ段階的に移行する。
