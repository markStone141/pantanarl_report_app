# Cloud Run Deployment

## 1. Prerequisites

- GCP project created
- Billing enabled
- APIs enabled:
  - `run.googleapis.com`
  - `cloudbuild.googleapis.com`
  - `artifactregistry.googleapis.com`
  - `sqladmin.googleapis.com` (if using Cloud SQL)

## 2. Required env vars

Set these on Cloud Run (or via deploy command):

- `DJANGO_SETTINGS_MODULE=config.settings.prod`
- `SECRET_KEY=<strong-random-secret>`
- `ALLOWED_HOSTS=<cloud-run-hostname-or-custom-domain>`
- `CSRF_TRUSTED_ORIGINS=https://<cloud-run-hostname-or-custom-domain>`

If using PostgreSQL (Cloud SQL):

- `DB_ENGINE=django.db.backends.postgresql`
- `DB_NAME=<database-name>`
- `DB_USER=<database-user>`
- `DB_PASSWORD=<database-password>`
- `DB_HOST=/cloudsql/<PROJECT:REGION:INSTANCE>`
- `DB_PORT=5432`

Optional startup flags:

- `RUN_MIGRATIONS_ON_STARTUP=1`
- `RUN_SEED_ON_STARTUP=1`

## 3. One-time Artifact Registry setup

```bash
gcloud artifacts repositories create report-app \
  --repository-format=docker \
  --location=asia-northeast1
```

## 4. Deploy with Cloud Build

Run from `backend/`:

```bash
gcloud builds submit --config cloudbuild.yaml \
  --substitutions _SERVICE=report-app,_REGION=asia-northeast1,_REPOSITORY=report-app
```

## 5. First deploy checklist

1. Deploy once with `RUN_MIGRATIONS_ON_STARTUP=1`.
2. If needed, also set `RUN_SEED_ON_STARTUP=1` for initial department/metric defaults.
3. After first successful boot, set both flags back to `0`.

## 6. Recommended operation

- Use Secret Manager for `SECRET_KEY` and DB credentials.
- Keep `RUN_MIGRATIONS_ON_STARTUP=0` for normal runtime.
- Run schema migrations in release pipeline before traffic cutover.
