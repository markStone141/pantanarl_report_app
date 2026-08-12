# Git bundleによるPUSH引き渡し工程

ChatGPTの作業環境からGitHubへ直接PUSHできない場合は、監査済みの作業ブランチをGit bundleとして受け渡し、利用者のPCからGitHubへPUSHする。

## 適用条件

- ローカル監査と必要なテストが完了している。
- 作業ツリーに意図しない未コミット変更がない。
- PUSH対象ブランチと最新コミットが確定している。
- ユーザーからPUSH工程へ進む明示指示がある。

## この案件のデフォルトPUSH方式

この報告アプリ案件では、ユーザーが「PUSH」「次の工程」などPUSH工程への移行を指示した時点で、ChatGPT作業環境から直接PUSHできるかを改めて試さない。GitHub CLI（`gh`）や認証状態の確認を先行させず、最初から次の一連の流れを開始する。

1. ChatGPT作業環境で監査済みブランチのbundleを作成する。
2. bundleの完全性、収録ブランチ、最新コミットを検証する。
3. ユーザーがbundleをダウンロードする。
4. ユーザーのWSLで `/mnt/e/Downloads` のbundleから未使用の別フォルダーへcloneする。
5. clone直後のHEADが案内済みコミットIDと一致することを確認する。
6. `origin`をGitHubへ変更し、通常の`git push`を実行する。
7. GitHub側の対象ブランチの最新コミットを照合して完了とする。

ユーザーに直接PUSH方式との選択を毎回求めたり、`gh`未導入を理由に停止したりしない。PR作成・CI確認・公開はPUSH完了後の別工程とする。

## 1. ChatGPT作業環境でbundleを作る

リポジトリルートで対象ブランチと状態を確認する。

```bash
git status --short --branch
git branch --show-current
git log -1 --oneline
git fetch origin
git rev-list --count origin/main..HEAD
```

作業ブランチだけをbundleへ収録する。

```bash
git bundle create pantanarl_report_app_<最新コミット短縮ID>.bundle \
  refactor/performance-today-details
```

作成後は必ず完全性と収録参照を確認する。

```bash
git bundle verify pantanarl_report_app_<最新コミット短縮ID>.bundle
git bundle list-heads pantanarl_report_app_<最新コミット短縮ID>.bundle
```

確認結果として、対象ブランチが表示され、`git bundle verify` が成功してからファイルを渡す。

## 2. 利用者のWSLでbundleから復元する（標準手順）

利用者側の標準環境はWSLで、ダウンロード先は `/mnt/e/Downloads` とする。
既存フォルダーを再利用すると古いブランチをPUSHする危険があるため、最新コミットIDを含む新しい別フォルダーへcloneする。

コマンドは改行による入力事故を避けるため、1行ずつ実行する。

```bash
git clone --branch refactor/performance-today-details /mnt/e/Downloads/pantanarl_report_app_<最新コミット短縮ID>.bundle /mnt/e/Downloads/pantanarl_report_app_push_<最新コミット短縮ID>
```

```bash
cd /mnt/e/Downloads/pantanarl_report_app_push_<最新コミット短縮ID>
```

同名フォルダーが既にある場合は、削除・上書き・再利用をせず、末尾に日時などを付けた未使用の別名へcloneする。

```bash
git clone --branch refactor/performance-today-details /mnt/e/Downloads/pantanarl_report_app_<最新コミット短縮ID>.bundle /mnt/e/Downloads/pantanarl_report_app_push_<最新コミット短縮ID>_YYYYMMDDHHMM
```

## 3. GitHubをPUSH先に設定する

bundleからcloneした直後の `origin` はbundleファイルを指しているため、GitHubへ変更する。

```bash
git remote set-url origin https://github.com/markStone141/pantanarl_report_app.git
git remote -v
```

表示されたfetch・pushの両方がGitHub URLであることを確認する。

## 4. PUSH前の最終確認

```bash
git status --short --branch
git branch --show-current
git rev-parse --short HEAD
git log -1 --oneline
```

次を満たすことを確認する。

- ブランチ: `refactor/performance-today-details`
- `git rev-parse --short HEAD`: bundle作成時に案内された最新コミットIDと完全一致
- 作業ツリー: clean

期待するコミットIDと一致しない場合はPUSHしない。既存フォルダーや別のcloneを使っていないか確認し、新しい別フォルダーへcloneし直す。

## 5. 作業ブランチをGitHubへPUSHする

```bash
git push -u origin HEAD:refactor/performance-today-details
```

GitHubの認証画面が出た場合は、利用者自身のGitHubアカウントで認証する。パスワードやトークンはChatGPTへ送らない。

PUSHにはGitHub CLI（`gh`）を必要としない。`gh`が未導入でも、通常の `git push` を実行する。`gh`が必要になるPR作成は次工程として分ける。

PUSH後は、出力が `Everything up-to-date` であっても、それだけでは成功と判断しない。GitHub上の `refactor/performance-today-details` の最新コミットが、bundle作成時に案内されたコミットIDと一致することを確認してPUSH完了とする。

Pull Request作成・CI確認・公開は別工程で行う。`main` へ直接PUSHしない。

## 6. PUSH後の工程

1. GitHub上のブランチと最新コミットを確認する。
2. Pull Requestの差分とCI結果を確認する。
3. `main` へマージする。
4. デプロイ結果を確認する。
5. 公開環境でPC／モバイルの主要導線を確認する。
6. `PROJECT_STATE.md` と作業ログへPUSH・公開状態を記録する。

## 問題が起きた場合

- `destination path already exists`: 既存フォルダーへ移動して続行しない。clone先を未使用の別名へ変え、bundleからcloneし直す。
- `Everything up-to-date`: 既存cloneや古いブランチからPUSHしていないか疑い、ローカルHEADとGitHub側の対象ブランチのコミットIDを照合する。一致するまで完了扱いにしない。
- `remote origin already exists`: `git remote add` ではなく `git remote set-url` を使う。
- `src refspec ... does not match any`: `git branch --show-current` と `git bundle list-heads` を確認する。
- `non-fast-forward`: 強制PUSHせず、GitHub側の同名ブランチとの差分を確認して作業を停止する。
- 認証エラー: GitHubのブラウザー認証またはCredential Managerを使い、認証情報をチャットへ貼らない。

## エージェントが守る既定動作

- この案件のPUSH依頼では、自分で直接PUSHを試してから失敗する流れを繰り返さない。常にbundle・WSL方式から開始する。
- ユーザーが「次の工程」と指示し、PUSH工程が合意済みなら、送信先・ブランチ・コミットを同じ内容で繰り返し確認しない。
- ChatGPT環境から直接PUSHできない場合は、bundle作成・ダウンロード後に、このWSL手順を案内する。
- `/mnt/e/Downloads` をWSLから参照する。Windows PowerShell用コマンドへ置き換えない。
- clone、HEAD確認、remote変更、PUSHを一連の工程として扱う。
- `gh`未導入を理由にPUSH前で停止しない。
- PUSH後のリモートコミット照合までをPUSH工程の完了条件とする。
- PR作成・CI・公開は、PUSH完了後の別工程として扱う。
