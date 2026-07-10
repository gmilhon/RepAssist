#!/usr/bin/env bash
# Deploy Rep Assist to Google Cloud Run.
# Usage: ./deploy.sh [--project PROJECT_ID] [--region REGION]
#
# Prerequisites:
#   gcloud CLI installed and authenticated (gcloud auth login)
#   gcloud config set project YOUR_PROJECT_ID
#   Docker Desktop running (used by Cloud Build)
set -euo pipefail

# --------------------------------------------------------------------------- #
# Config (override via flags or env)
# --------------------------------------------------------------------------- #
PROJECT="${GCLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GCLOUD_REGION:-us-central1}"
SERVICE="rep-assist"
IMAGE="gcr.io/${PROJECT}/${SERVICE}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --project) PROJECT="$2"; IMAGE="gcr.io/${PROJECT}/${SERVICE}"; shift 2 ;;
    --region)  REGION="$2"; shift 2 ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

if [[ -z "$PROJECT" ]]; then
  echo "ERROR: No GCP project set. Run: gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi

echo "▶ Project : $PROJECT"
echo "▶ Region  : $REGION"
echo "▶ Image   : $IMAGE"
echo ""

# --------------------------------------------------------------------------- #
# 1. Enable required APIs (idempotent)
# --------------------------------------------------------------------------- #
echo "── Enabling GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  containerregistry.googleapis.com \
  secretmanager.googleapis.com \
  --project "$PROJECT" -q

# --------------------------------------------------------------------------- #
# 2. Create secrets (skip if they already exist)
# --------------------------------------------------------------------------- #
echo "── Setting up secrets..."

create_secret_if_missing() {
  local name=$1 prompt=$2
  if ! gcloud secrets describe "$name" --project "$PROJECT" &>/dev/null; then
    echo -n "  Enter value for $name ($prompt): "
    read -rs value; echo ""
    printf '%s' "$value" | gcloud secrets create "$name" \
      --data-file=- --project "$PROJECT" -q
    echo "  ✓ Created secret: $name"
  else
    echo "  ✓ Secret exists: $name"
  fi
}

create_secret_if_missing "rep-assist-anthropic-key"  "ANTHROPIC_API_KEY"
create_secret_if_missing "rep-assist-langsmith-key"  "LANGCHAIN_API_KEY (or leave blank and press Enter)"

# --------------------------------------------------------------------------- #
# 3. Build frontend
# --------------------------------------------------------------------------- #
echo "── Building React frontend..."
cd "$(dirname "$0")/frontend"
npm ci --silent
npm run build
cd ..

# --------------------------------------------------------------------------- #
# 4. Bundle frontend into backend/static for the Docker image
# --------------------------------------------------------------------------- #
echo "── Bundling frontend into backend/static..."
rm -rf backend/static
cp -r frontend/dist backend/static

# --------------------------------------------------------------------------- #
# 5. Build and push Docker image via Cloud Build
# --------------------------------------------------------------------------- #
echo "── Building Docker image with Cloud Build..."
gcloud builds submit backend/ \
  --tag "$IMAGE" \
  --project "$PROJECT"

# --------------------------------------------------------------------------- #
# 6. Deploy to Cloud Run
# --------------------------------------------------------------------------- #
echo "── Deploying to Cloud Run..."
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --platform managed \
  --region "$REGION" \
  --project "$PROJECT" \
  --allow-unauthenticated \
  --min-instances 1 \
  --max-instances 1 \
  --memory 1Gi \
  --cpu 1 \
  --timeout 60 \
  --set-secrets "ANTHROPIC_API_KEY=rep-assist-anthropic-key:latest" \
  --set-secrets "LANGCHAIN_API_KEY=rep-assist-langsmith-key:latest" \
  --set-env-vars "LANGCHAIN_PROJECT=rep-assist,ANTHROPIC_MODEL=claude-opus-4-8"

# --------------------------------------------------------------------------- #
# 7. Print the URL
# --------------------------------------------------------------------------- #
URL=$(gcloud run services describe "$SERVICE" \
  --platform managed \
  --region "$REGION" \
  --project "$PROJECT" \
  --format "value(status.url)")

echo ""
echo "✓ Deployed! Rep Assist is live at:"
echo "  $URL"
echo ""
echo "Next steps:"
echo "  • Set SMTP secrets for email reports:"
echo "    echo -n 'your-smtp-password' | gcloud secrets create rep-assist-smtp-password --data-file=- --project $PROJECT"
echo "    gcloud run services update $SERVICE --region $REGION --project $PROJECT \\"
echo "      --set-secrets SMTP_PASSWORD=rep-assist-smtp-password:latest \\"
echo "      --set-env-vars SMTP_HOST=smtp.gmail.com,SMTP_USER=your@gmail.com,SMTP_FROM='Rep Assist <your@gmail.com>'"
echo ""
echo "  • To update secrets:"
echo "    gcloud secrets versions add rep-assist-anthropic-key --data-file=- --project $PROJECT"
