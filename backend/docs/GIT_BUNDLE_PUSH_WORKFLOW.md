# Git bundleによるPUSH引き渡し工程

ChatGPTの作業環境からGitHubへ直接PUSHできない場合は、監査済みの作業ブランチをGit bundleとして受け渡し、利用者のPCからGitHubへPUSHする。

## 適用条件

- ローカル監査と必要なテストが完了している。
- 作業ツリーに意図しない未コミット変更がない。
- PUSH対象ブランチと最新コミットが確定している。
- ユーザーからPUSH工程へ進む明示指示がある。

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

## 2. 利用者のPCでbundleから復元する

ダウンロードしたbundleがあるフォルダーで実行する。

```powershell
git clone -b refactor/performance-today-details `
  .\pantanarl_report_app_<最新コミット短縮ID>.bundle `
  pantanarl_report_app
cd pantanarl_report_app
```

同名フォルダーが既にある場合は上書きせず、別名のフォルダーへcloneする。

## 3. GitHubをPUSH先に設定する

bundleからcloneした直後の `origin` はbundleファイルを指しているため、GitHubへ変更する。

```powershell
git remote set-url origin https://github.com/markStone141/pantanarl_report_app.git
git remote -v
```

表示されたfetch・pushの両方がGitHub URLであることを確認する。

## 4. PUSH前の最終確認

```powershell
git status --short --branch
git branch --show-current
git log -1 --oneline
```

次を満たすことを確認する。

- ブランチ: `refactor/performance-today-details`
- HEAD: bundle作成時に案内された最新コミット
- 作業ツリー: clean

## 5. 作業ブランチをGitHubへPUSHする

```powershell
git push -u origin refactor/performance-today-details
```

GitHubの認証画面が出た場合は、利用者自身のGitHubアカウントで認証する。パスワードやトークンはChatGPTへ送らない。

PUSH後はGitHub上で同ブランチの最新コミットを確認し、Pull Requestを作成してレビュー後に `main` へマージする。`main` へ直接PUSHしない。

## 6. PUSH後の工程

1. GitHub上のブランチと最新コミットを確認する。
2. Pull Requestの差分とCI結果を確認する。
3. `main` へマージする。
4. デプロイ結果を確認する。
5. 公開環境でPC／モバイルの主要導線を確認する。
6. `PROJECT_STATE.md` と作業ログへPUSH・公開状態を記録する。

## 問題が起きた場合

- `destination path already exists`: clone先のフォルダー名を変える。
- `remote origin already exists`: `git remote add` ではなく `git remote set-url` を使う。
- `src refspec ... does not match any`: `git branch --show-current` と `git bundle list-heads` を確認する。
- `non-fast-forward`: 強制PUSHせず、GitHub側の同名ブランチとの差分を確認して作業を停止する。
- 認証エラー: GitHubのブラウザー認証またはCredential Managerを使い、認証情報をチャットへ貼らない。
