#!/usr/bin/env bash
# Put the site online: the API on Cloud Run, the pages on Firebase Hosting.
#   ./deploy.sh <firebase-project-id>
set -euo pipefail
PROJECT="${1:?usage: ./deploy.sh <firebase-project-id>}"
REGION=us-central1
cd "$(dirname "$0")"

if [ ! -f data/campsites.db ]; then
  echo "data/campsites.db is missing. Run: python3 manage.py import-seed" >&2
  exit 1
fi

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  --project "$PROJECT"
gcloud run deploy campsite-api --source . --project "$PROJECT" --region "$REGION" \
  --allow-unauthenticated --memory 512Mi --max-instances 2 --quiet
firebase deploy --only hosting --project "$PROJECT"
