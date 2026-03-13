#!/bin/sh
set -eu

ACTION="${1:-}"

if [ -z "$ACTION" ]; then
  echo "Usage: $0 <upsert|run>" >&2
  exit 1
fi

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
REGION="${REGION:-asia-northeast1}"
REPOSITORY="${REPOSITORY:-report-app}"
SERVICE="${SERVICE:-report-app}"
JOB_NAME="${JOB_NAME:-${SERVICE}-migrate}"
IMAGE="${IMAGE:-}"
DB_INSTANCE="${DB_INSTANCE:-}"
ENV_VARS="${ENV_VARS:-DJANGO_SETTINGS_MODULE=config.settings.prod}"
SECRETS="${SECRETS:-}"

normalize_csv_args() {
  printf '%s' "$1" | tr '\r\n' ',' | sed 's/[[:space:]]*,[[:space:]]*/,/g; s/^,*//; s/,*$//'
}

if [ -z "$PROJECT_ID" ]; then
  echo "PROJECT_ID is required. Set PROJECT_ID or configure gcloud default project." >&2
  exit 1
fi

if [ -z "$IMAGE" ]; then
  IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${SERVICE}:latest"
fi

ENV_VARS="$(normalize_csv_args "$ENV_VARS")"
SECRETS="$(normalize_csv_args "$SECRETS")"

BASE_ARGS="
  --project=${PROJECT_ID}
  --region=${REGION}
  --image=${IMAGE}
  --command=python
  --args=manage.py
  --args=migrate
  --args=--noinput
  --set-env-vars=${ENV_VARS}
"

if [ -n "$DB_INSTANCE" ]; then
  BASE_ARGS="${BASE_ARGS} --set-cloudsql-instances=${DB_INSTANCE}"
fi

if [ -n "$SECRETS" ]; then
  BASE_ARGS="${BASE_ARGS} --set-secrets=${SECRETS}"
fi

case "$ACTION" in
  upsert)
    if gcloud run jobs describe "$JOB_NAME" --project="$PROJECT_ID" --region="$REGION" >/dev/null 2>&1; then
      # shellcheck disable=SC2086
      gcloud run jobs update "$JOB_NAME" $BASE_ARGS
    else
      # shellcheck disable=SC2086
      gcloud run jobs create "$JOB_NAME" $BASE_ARGS
    fi
    ;;
  run)
    gcloud run jobs execute "$JOB_NAME" --project="$PROJECT_ID" --region="$REGION" --wait
    ;;
  *)
    echo "Unknown action: $ACTION" >&2
    echo "Usage: $0 <upsert|run>" >&2
    exit 1
    ;;
esac
