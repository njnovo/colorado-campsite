#!/usr/bin/env bash
# One-time setup so GitHub Actions can deploy (see .github/workflows/deploy.yml).
# Lets only the njnovo/colorado-campsite repo act as the github-deployer account.
set -euo pipefail
PROJECT=colorado-campsite
NUMBER=476726919278
REPO=njnovo/colorado-campsite
SA=github-deployer@$PROJECT.iam.gserviceaccount.com

gcloud services enable iamcredentials.googleapis.com sts.googleapis.com --project "$PROJECT"

gcloud iam workload-identity-pools describe github --location=global --project "$PROJECT" >/dev/null 2>&1 ||
  gcloud iam workload-identity-pools create github --location=global --project "$PROJECT" \
    --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers describe github --location=global \
    --workload-identity-pool=github --project "$PROJECT" >/dev/null 2>&1 ||
  gcloud iam workload-identity-pools providers create-oidc github --location=global \
    --workload-identity-pool=github --project "$PROJECT" --display-name="GitHub" \
    --issuer-uri=https://token.actions.githubusercontent.com \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition="assertion.repository=='$REPO'"

gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1 ||
  gcloud iam service-accounts create github-deployer --project "$PROJECT" \
    --display-name="GitHub Actions deployer"

for role in roles/run.admin roles/run.sourceDeveloper roles/iam.serviceAccountUser \
            roles/serviceusage.serviceUsageConsumer roles/firebasehosting.admin; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" \
    --role="$role" --condition=None >/dev/null
  echo "granted $role"
done

gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$PROJECT" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$REPO" \
  >/dev/null
echo "Done: GitHub Actions in $REPO can now deploy."
