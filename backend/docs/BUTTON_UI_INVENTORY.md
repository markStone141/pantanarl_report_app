# 共通ボタンUI台帳（工程11）

最終更新日: 2026-08-12

## 分類基準

| 分類 | 主な操作 | 共通クラス |
|---|---|---|
| Primary | 保存、登録、送信、次へ | `.ui-button.ui-button--primary` |
| Secondary | 編集、詳細、追加表示、戻る | `.ui-button.ui-button--secondary` |
| Quiet | キャンセル、閉じる、リセット | `.ui-button.ui-button--quiet` |
| Danger | 削除、無効化、活動終了 | `.ui-button.ui-button--danger` |
| Icon | 表内の編集、削除、お気に入り | `.ui-icon-button` |
| Choice | タブ、フィルタ、表示切替 | `.ui-choice-button` |

## 監査結果

- 共通 `.btn-inline` は100件以上あり、意味の異なる操作へ同じ外観が使われている。
- `button` の既定スタイルはグラデーションと大きな影を使い、共通NAVの平面的で落ち着いた外観との差が大きい。
- `dairymetrics`、`talks`、`testimony`、`mosaic`、`monthly_guide` には固有クラスがあり、工程11-2／11-3で機能単位に分類して移行する。
- 一括置換はせず、URL、権限、送信処理、AJAXの契約を維持したままアプリ単位で移行する。

## 11-1代表適用

| 画面 | 操作 | 分類 |
|---|---|---|
| dashboard 管理トップ | テンプレート生成 | Primary |
| dashboard 管理トップ | 報告修正、コピー | Secondary |
| dashboard 管理トップ | モーダルを閉じる | Quiet |
| dashboard 管理トップ | 本日／前日表示 | Choice |
| performance 補正実績 | 補正実績を保存／更新 | Primary |
| performance 補正実績 | 追加読み込み | Secondary |
| performance 補正実績 | キャンセル、リセット | Quiet |
| performance 補正実績 | 表内編集 | Icon |
| performance 補正実績 | 表内削除 | Icon + Danger |

## 今後の移行順

1. 工程11-2で `dashboard`、`performance`、`targets`、`mail`、`reports`、`dairymetrics` を移行する。
2. 工程11-3で `talks`、`testimony`、`monthly_guide`、`mosaic`、`accounts` を移行する。
3. 工程11-4で旧クラス、モバイル、キーボード、状態表示を横断監査する。

## 11-4 横断監査

- 共通クラスなしで残る `.btn-inline` は36件。
- 21件はページ番号または前後ページ移動で、Primary／Secondaryなどの業務操作とは異なるナビゲーション要素として既存のコンパクト表示を維持する。
- 15件はモバイルのドロワーメニュー開閉で、40pxの固定タップ領域と既存JavaScript参照を維持するため固有クラスを残す。
- 保存、登録、送信、編集、削除、閉じる、表示切替に、共通分類のない移行漏れは確認されなかった。
- 固有クラスと共通クラスの併記は、既存ID、JavaScript、フォーム、配置を維持する互換層として残す。用途が固有でない新規ボタンでは共通クラスを優先する。
- `docs/button-ui-preview.html` は外部CSS参照をなくし、チャットのファイルリンクから直接開いても完成デザインが表示される自己完結HTMLへ変更した。
