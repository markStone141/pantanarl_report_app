begin;

-- PostgREST / Supabase API 用ロールから public スキーマの既存権限を外す
revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke all on all functions in schema public from anon, authenticated;

-- 今後 postgres が public スキーマに作るオブジェクトも同じ方針にする
alter default privileges for role postgres in schema public
revoke all on tables from anon, authenticated;

alter default privileges for role postgres in schema public
revoke all on sequences from anon, authenticated;

alter default privileges for role postgres in schema public
revoke all on functions from anon, authenticated;

-- public スキーマ上の Django テーブル群は API 公開前提ではないため、
-- 一律で RLS を有効化して policy 未定義時は読めない状態にする
do $$
declare
    table_name text;
begin
    for table_name in
        select tablename
        from pg_tables
        where schemaname = 'public'
    loop
        execute format('alter table public.%I enable row level security', table_name);
        execute format('alter table public.%I force row level security', table_name);
    end loop;
end
$$;

commit;
