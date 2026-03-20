# Supabase Security Hardening

このプロジェクトは Supabase を Django の PostgreSQL として利用しており、Supabase の REST API / PostgREST で
`public` スキーマのテーブルを直接使う前提ではありません。

そのため、Django テーブルは「DB としては使えるが、Supabase API 面からは見えない」状態に寄せるのが安全です。

## 推奨対応

1. `backend/docs/sql/supabase_harden_public_schema.sql` を Supabase SQL Editor で実行する
2. Supabase linter を再実行する
3. 将来 PostgREST で公開したいテーブルが出た場合だけ、個別に policy を追加する

## 何をしているか

この SQL は次を行います。

- `anon` / `authenticated` から `public` スキーマの既存テーブル・シーケンス・関数権限を剥がす
- 今後 `postgres` が `public` に作るオブジェクトにも同じ revoke をかける
- `public` の全テーブルで RLS を有効化する
- `public` の全テーブルで `FORCE ROW LEVEL SECURITY` を有効化する

## Django への影響

このリポジトリの本番想定では、Django は DB ユーザーとして `postgres` を使って接続しています。
そのため、Supabase API 用の `anon` / `authenticated` ロールを締めても、通常の Django アプリ動作には影響しにくいです。

ただし、Supabase 側の接続ユーザーや権限構成を変えている場合は、実行前に必ず確認してください。

## 注意

- PostgREST / Supabase REST API で `public` のテーブルを直接使いたい場合は、この SQL をそのまま入れず、対象テーブルだけ個別に policy 設計してください
- `auth_user.password` が「漏れても問題ない」運用であっても、API 面を広く開ける理由にはなりません。今回の SQL では `auth_user` も含めて閉じます
