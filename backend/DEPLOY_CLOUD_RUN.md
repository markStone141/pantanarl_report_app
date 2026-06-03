# Cloud Run Deployment

## 1. Prerequisites

- GCP project created
- Billing enabled
- APIs enabled:
  - `run.googleapis.com`
  - `cloudbuild.googleapis.com`
  - `artifactregistry.googleapis.com`

## 2. Required env vars

Set these on Cloud Run (or via deploy command):

- `DJANGO_SETTINGS_MODULE=config.settings.prod`
- `SECRET_KEY=<strong-random-secret>`
- `ALLOWED_HOSTS=<cloud-run-hostname-or-custom-domain>`
- `CSRF_TRUSTED_ORIGINS=https://<cloud-run-hostname-or-custom-domain>`

If using PostgreSQL (Supabase / external PostgreSQL):

- `DB_ENGINE=django.db.backends.postgresql`
- `DB_NAME=<database-name>`
- `DB_USER=<database-user>`
- `DB_PASSWORD=<database-password>`
- `DB_HOST=<database-host>`
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

## 4.1 Deploy with GitHub Actions

This repository also has `.github/workflows/deploy-cloud-run.yml`.
When `main` is updated, GitHub Actions will:

1. build the backend image
2. push it to Artifact Registry
3. deploy `report-app`
4. upsert the migration job
5. execute the migration job
6. upsert the activity reminder job with the same image

Required GitHub secrets:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`

Optional GitHub repository variables:

- `CLOUD_RUN_MIGRATE_JOB_ENV_VARS`
- `CLOUD_RUN_MIGRATE_JOB_SECRETS`
- `CLOUD_RUN_ACTIVITY_REMINDER_JOB_ENV_VARS`
- `CLOUD_RUN_ACTIVITY_REMINDER_JOB_SECRETS`

## 5. First deploy checklist

1. Deploy once with `RUN_MIGRATIONS_ON_STARTUP=1`.
2. If needed, also set `RUN_SEED_ON_STARTUP=1` for initial department/metric defaults.
3. After first successful boot, set both flags back to `0`.

## 6. Recommended operation

- Use Secret Manager for `SECRET_KEY` and DB credentials.
- Keep `RUN_MIGRATIONS_ON_STARTUP=0` for normal runtime.
- Run schema migrations in release pipeline before traffic cutover.

## 7. Cloud Run Job for migrations

Running migrations in a dedicated Cloud Run Job is safer than doing it during web startup.

Prepare or update the job:

```bash
cd backend
chmod +x scripts/cloud_run_migrate_job.sh
PROJECT_ID=<gcp-project-id> \
REGION=asia-northeast1 \
REPOSITORY=report-app \
SERVICE=report-app \
IMAGE=asia-northeast1-docker.pkg.dev/<gcp-project-id>/report-app/report-app:<image-tag> \
ENV_VARS='DJANGO_SETTINGS_MODULE=config.settings.prod,ALLOWED_HOSTS=<host>,CSRF_TRUSTED_ORIGINS=https://<host>,DB_ENGINE=django.db.backends.postgresql,DB_NAME=<db-name>,DB_USER=<db-user>,DB_HOST=<db-host>,DB_PORT=5432' \
SECRETS='SECRET_KEY=SECRET_KEY:latest,DB_PASSWORD=DB_PASSWORD:latest' \
./scripts/cloud_run_migrate_job.sh upsert
```

Execute the job:

```bash
cd backend
PROJECT_ID=<gcp-project-id> \
REGION=asia-northeast1 \
SERVICE=report-app \
./scripts/cloud_run_migrate_job.sh run
```

Notes:

- If `IMAGE` is omitted, the script falls back to `:latest`.
- `SECRETS` accepts the same format as `gcloud run jobs create --set-secrets`.
- Use the same image tag for both the web deploy and the migration job.

## 8. Cloud Run Job for activity close reminders

The activity close reminder job sends email to active members who still have an open activity entry.
It is intended to run every day at 19:00 JST via Cloud Scheduler.

Prepare or update the job and scheduler manually:

```bash
cd backend
chmod +x scripts/cloud_run_activity_reminder_job.sh
PROJECT_ID=<gcp-project-id> \
REGION=asia-northeast1 \
REPOSITORY=report-app \
SERVICE=report-app \
IMAGE=asia-northeast1-docker.pkg.dev/<gcp-project-id>/report-app/report-app:<image-tag> \
ENV_VARS='DJANGO_SETTINGS_MODULE=config.settings.prod,ALLOWED_HOSTS=<host>,CSRF_TRUSTED_ORIGINS=https://<host>,DB_ENGINE=django.db.backends.postgresql,DB_NAME=<db-name>,DB_USER=<db-user>,DB_HOST=<db-host>,DB_PORT=5432' \
SECRETS='SECRET_KEY=SECRET_KEY:latest,DB_PASSWORD=DB_PASSWORD:latest' \
SCHEDULER_SERVICE_ACCOUNT=<scheduler-service-account>@<gcp-project-id>.iam.gserviceaccount.com \
./scripts/cloud_run_activity_reminder_job.sh upsert-all
```

After this initial setup, GitHub Actions updates the Cloud Run Job image on every `main` deployment.
The Cloud Scheduler job can keep pointing to the same `report-app-activity-reminder` job.

Run the job manually:

```bash
cd backend
PROJECT_ID=<gcp-project-id> \
REGION=asia-northeast1 \
SERVICE=report-app \
./scripts/cloud_run_activity_reminder_job.sh run
```

Notes:

- Default schedule is `0 19 * * *` with `Asia/Tokyo` time zone.
- The scheduler service account needs permission to run the Cloud Run Job.
- The app also prevents duplicate same-day reminder emails per member.
