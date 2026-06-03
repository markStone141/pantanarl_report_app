#!/bin/sh
set -eu

ACTION="${1:-}"

if [ -z "$ACTION" ]; then
  echo "Usage: $0 <upsert-job|run|upsert-scheduler|upsert-all>" >&2
  exit 1
fi

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
REGION="${REGION:-asia-northeast1}"
SCHEDULER_LOCATION="${SCHEDULER_LOCATION:-${REGION}}"
REPOSITORY="${REPOSITORY:-report-app}"
SERVICE="${SERVICE:-report-app}"
JOB_NAME="${JOB_NAME:-${SERVICE}-activity-reminder}"
SCHEDULER_JOB_NAME="${SCHEDULER_JOB_NAME:-${JOB_NAME}-scheduler}"
IMAGE="${IMAGE:-}"
DB_INSTANCE="${DB_INSTANCE:-}"
ENV_VARS="${ENV_VARS:-DJANGO_SETTINGS_MODULE=config.settings.prod}"
SECRETS="${SECRETS:-}"
SCHEDULE="${SCHEDULE:-0 19 * * *}"
TIME_ZONE="${TIME_ZONE:-Asia/Tokyo}"
SCHEDULER_SERVICE_ACCOUNT="${SCHEDULER_SERVICE_ACCOUNT:-}"

normalize_csv_args() {
  printf '%s' "$1" | tr '\r\n' ',' | sed 's/[[:space:]]*,[[:space:]]*/,/g; s/^,*//; s/,*$//'
}

require_project() {
  if [ -z "$PROJECT_ID" ]; then
    echo "PROJECT_ID is required. Set PROJECT_ID or configure gcloud default project." >&2
    exit 1
  fi
}

resolve_image() {
  if [ -z "$IMAGE" ]; then
    IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${SERVICE}:latest"
  fi
}

upsert_job() {
  require_project
  resolve_image
  ENV_VARS="$(normalize_csv_args "$ENV_VARS")"
  SECRETS="$(normalize_csv_args "$SECRETS")"

  BASE_ARGS="
    --project=${PROJECT_ID}
    --region=${REGION}
    --image=${IMAGE}
    --command=python
    --args=manage.py
    --args=send_activity_close_reminders
    --set-env-vars=${ENV_VARS}
    --tasks=1
    --max-retries=0
    --task-timeout=600s
  "

  if [ -n "$DB_INSTANCE" ]; then
    BASE_ARGS="${BASE_ARGS} --set-cloudsql-instances=${DB_INSTANCE}"
  fi

  if [ -n "$SECRETS" ]; then
    BASE_ARGS="${BASE_ARGS} --set-secrets=${SECRETS}"
  fi

  if gcloud run jobs describe "$JOB_NAME" --project="$PROJECT_ID" --region="$REGION" >/dev/null 2>&1; then
    # shellcheck disable=SC2086
    gcloud run jobs update "$JOB_NAME" $BASE_ARGS
  else
    # shellcheck disable=SC2086
    gcloud run jobs create "$JOB_NAME" $BASE_ARGS
  fi
}

run_job() {
  require_project
  gcloud run jobs execute "$JOB_NAME" --project="$PROJECT_ID" --region="$REGION" --wait
}

upsert_scheduler() {
  require_project
  if [ -z "$SCHEDULER_SERVICE_ACCOUNT" ]; then
    echo "SCHEDULER_SERVICE_ACCOUNT is required for Cloud Scheduler OAuth." >&2
    exit 1
  fi

  RUN_URI="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB_NAME}:run"

  if gcloud scheduler jobs describe "$SCHEDULER_JOB_NAME" --project="$PROJECT_ID" --location="$SCHEDULER_LOCATION" >/dev/null 2>&1; then
    gcloud scheduler jobs update http "$SCHEDULER_JOB_NAME" \
      --project="$PROJECT_ID" \
      --location="$SCHEDULER_LOCATION" \
      --schedule="$SCHEDULE" \
      --time-zone="$TIME_ZONE" \
      --uri="$RUN_URI" \
      --http-method=POST \
      --oauth-service-account-email="$SCHEDULER_SERVICE_ACCOUNT" \
      --headers=Content-Type=application/json \
      --message-body="{}"
  else
    gcloud scheduler jobs create http "$SCHEDULER_JOB_NAME" \
      --project="$PROJECT_ID" \
      --location="$SCHEDULER_LOCATION" \
      --schedule="$SCHEDULE" \
      --time-zone="$TIME_ZONE" \
      --uri="$RUN_URI" \
      --http-method=POST \
      --oauth-service-account-email="$SCHEDULER_SERVICE_ACCOUNT" \
      --headers=Content-Type=application/json \
      --message-body="{}"
  fi
}

case "$ACTION" in
  upsert-job)
    upsert_job
    ;;
  run)
    run_job
    ;;
  upsert-scheduler)
    upsert_scheduler
    ;;
  upsert-all)
    upsert_job
    upsert_scheduler
    ;;
  *)
    echo "Unknown action: $ACTION" >&2
    echo "Usage: $0 <upsert-job|run|upsert-scheduler|upsert-all>" >&2
    exit 1
    ;;
esac
