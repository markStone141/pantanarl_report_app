# 全アプリUI・画面台帳

最終更新日: 2026-08-13

## 監査範囲

- Djangoの11アプリ、公開URL、画面テンプレート、権限、CSS／JavaScriptを対象とした。
- テンプレートはpartialを含めて78件ある。
- API、削除、更新、AJAX専用URLは画面数に含めず、関連する主画面の操作として扱う。
- 本台帳は工程3以降のUI展開順と共通化範囲を決める基準とする。

## アプリ別台帳

| アプリ | 主な画面・操作 | 主な利用者・権限 | 現在のUI基盤 | 主な監査結果 | 展開工程 |
|---|---|---|---|---|---|
| `accounts` | 共通ログイン、ログアウト | 管理者／報告者 | `base.html` + `app.css` | 単独画面。全体NAV確定後にログインとエラー表現を統一する。 | 工程9 |
| `dashboard` | 管理トップ、メンバー、ID一括、部署 | 管理者のみ | 共通CSS + `dashboard/mobile_drawer` | 管理設定系の中心。表・検索・長いフォームが混在し、NAV試験実装の対象に適する。 | 工程3・5 |
| `reports` | 報告入口、UN／WV等の入力、保存報告一覧、編集 | 報告者／管理者。履歴管理の一部は管理者 | 共通CSS + `dashboard/mobile_drawer` | 日常入力の主要導線。送信状態、エラー位置、長い入力、履歴操作を重点確認する。 | 工程6 |
| `targets` | 目標ダッシュボード、月目標、路程目標、履歴詳細 | 管理者のみ | 共通CSS + `targets/app.css` | 管理設定系。専用CSSはあるが共通ヘッダー／フォーム規則との整理余地が大きい。 | 工程5 |
| `performance` | 管理ダッシュボード、履歴、個人実績、補正、過去入力、全体管理 | 管理者中心。一部は報告者 | 共通CSS + `dashboard/mobile_drawer` + 機能別CSS/JS | 基準UI。画面数18で状態・AJAX・権限分岐が最多。NAV試験実装の対象。 | 工程1・3 |
| `dairymetrics` | 決済入力、分析、振り返り、エクスポート | 連携メンバー／管理者 | 共通CSS + `dairymetrics/app.css` + `dashboard/mobile_drawer` | 画面固有UIが強い。入力中・保存中・通知・展開表示を保持しながら共通ルールを適用する。 | 工程6 |
| `talks` | お知らせ一覧・詳細、投稿／コメント編集、タグ、削除管理 | ログインメンバー。管理操作は管理者 | 共通CSS + `talks/*` + 独自mobile drawer | 検索・未読・お気に入り・投稿管理がある。共通ドロワーと別実装で、統合対象。 | 工程3・7 |
| `testimony` | 証一覧・詳細・投稿、商品、マイページ、取込 | ログイン利用者。編集は本人／管理者 | `testimony/base.html` + 共通CSS | 画面数15。独自のアプリ内NAVとCRUDがあり、`talks` と記事部品を比較できる。 | 工程7 |
| `monthly_guide` | 月間案内の長文閲覧 | 主にログイン利用者 | 独立HTML + `monthly_guide/app.css` | 共通基盤から最も独立。長文の読みやすさと固有表現を優先し、無理にカード化しない。 | 工程8 |
| `mail` | 連携設定、宛先グループ、送信履歴 | 管理者のみ | 共通CSS + `dashboard/mobile_drawer` | 設定フォーム、選択リスト、履歴表が中心。管理設定系として統一効果が大きい。 | 工程5 |
| `mosaic` | 業務トップ、接客登録・一覧、マスター管理 | 専用ログイン。管理画面はstaff | `mosaic/base.html` + 専用CSS + `dashboard/mobile_drawer` | 独立した業務名と導線を維持する。共通ヘッダー・状態・フォーム規則だけを適用する。 | 工程8 |

## 横断監査結果

### NAVとヘッダー

- PC用メニューは複数画面で上部横並びになり、項目増加時に折り返しや密度上昇が起きる。
- モバイルドロワーは `dashboard/mobile_drawer` と `talks/mobile_drawer` の2系統がある。
- `testimony/base.html`、`mosaic/base.html`、`monthly_guide` はアプリ固有構造を持つ。
- 同じ利用者でも画面ごとに名称・順序・権限条件が変わり得るため、工程3でメニュー定義を一元化する。

### CSS

- 全体は `app.css` を使うが、`dairymetrics`、`targets`、`mosaic`、`monthly_guide`、`talks` に専用CSSがある。
- 専用CSSそのものは維持できるが、色、余白、角丸、見出し、ボタン、フォーム、状態表示の重複を工程4で共通変数・部品へ寄せる。
- インラインstyleを含むテンプレートが複数あるため、動的値以外は各アプリ展開時に整理する。

### 状態表示と操作

- 空状態やエラー表示は多くの画面にあるが、語調・位置・見た目が統一されていない。
- ローディング、送信中、二重送信防止は日常入力系とAJAX画面を中心に存在し、全画面共通ではない。
- 削除・編集・保存操作は `reports`、`performance`、`talks`、`testimony`、`mail`、`dashboard` に分散する。確認、成功、失敗の規則を共通化する必要がある。

## 優先順位

1. `dashboard` と `performance` でPCサイドNAV／スマホ共通ドロワーを試験実装する。
2. NAV確定後、共通トークンと基礎部品を整理する。
3. `dashboard`、`targets`、`mail` の管理設定系へ展開する。
4. `reports`、`dairymetrics` の日常入力系へ展開する。
5. `talks`、`testimony` の閲覧・検索・投稿系へ展開する。
6. `monthly_guide`、`mosaic` は固有構造を維持して最後に適用する。

## 工程3への引き渡し

- PCは左サイドNAV、スマホはグループ化ドロワーとする。
- PC／スマホで同じメニュー定義、名称、順番、権限条件を使う。
- 上部ヘッダーは現在ページ、短い説明、利用者、画面固有の主要操作に絞る。
- メニューは「日々の活動」「集計・振り返り」「情報共有」「管理・設定」「個別業務」「アカウント」を基準にする。
- `talks` の独自ドロワーを別系統として残さず、共通定義へ統合できる構造を設計する。

## 2026-08-13 完成監査

- 本番テンプレート86件のうち、共通シェル35件と意図したログイン・エラー・長文独立UIを確認した。
- 共通NAV、DairyMetrics、Mosaicのドロワーボタン3系統はすべて `ui-icon-button` を使用する。
- 旧 `topbar-menu-toggle`、`menu-collapsible`、`btn-inline dashboard-drawer-toggle` は0件。
- 残る `btn-inline` 57件は、ページング、コンパクトな編集・削除、Talks／Testimony／Mosaic／Monthly Guide固有操作のサイズ互換として維持する。ドロワー開閉には使用しない。
- PC幅1440pxとモバイル幅390pxの固定画像を `docs/ui-shell-desktop.png`、`docs/ui-shell-mobile.png` に更新した。
- 詳細な検証結果と公開判定は `UI_COMPLETION_AUDIT_2026-08-13.md` を参照する。
