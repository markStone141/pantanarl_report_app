# Backend Skeleton (Django)

Django本体のインストール前に、将来管理しやすい構成で骨格だけ作成しています。

## Directory

- `config/settings/base.py`, `local.py`, `prod.py`: settings分割
- `apps/`: ドメインごとのアプリ
  - `accounts`, `reports`, `targets`, `dashboard`, `talks`
- 各アプリは `models.py`, `views.py`, `urls.py`, `forms.py`, `services/`, `selectors/` を保持

## Next Steps

1. Python仮想環境を有効化
2. `pip install -r requirements/dev.txt`
3. `python manage.py migrate`
4. `python manage.py runserver`

## Note

この環境では外部ネットワーク制限があるため、`pip install django` は未実行です。
