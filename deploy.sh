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
  cloudbuild.googleapis.com \
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
create_secret_if_missing "rep-assist-smtp-password"  "SMTP_PASSWORD for email reports (or leave blank)"

# Admin token gates POST /api/admin/seed — auto-generate if missing.
if ! gcloud secrets describe "rep-assist-admin-token" --project "$PROJECT" &>/dev/null; then
  python3 -c "import secrets; print(secrets.token_hex(24))" \
    | tr -d '\n' \
    | gcloud secrets create "rep-assist-admin-token" --data-file=- --project "$PROJECT" -q
  echo "  ✓ Created secret: rep-assist-admin-token (auto-generated)"
else
  echo "  ✓ Secret exists: rep-assist-admin-token"
fi

# --------------------------------------------------------------------------- #
# 2b. Grant the Cloud Run runtime service account access to the secrets
# --------------------------------------------------------------------------- #
echo "── Granting Secret Manager access to the Cloud Run service account..."
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format "value(projectNumber)")
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member "serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role "roles/secretmanager.secretAccessor" \
  --project "$PROJECT" -q >/dev/null

# --------------------------------------------------------------------------- #
# 2c. Regenerate "What's new in Rep Assist" from recent git commits
# --------------------------------------------------------------------------- #
echo "── Refreshing System Enhancements from git history..."
if [[ -f backend/.venv/bin/python ]]; then
  (cd backend && .venv/bin/python scripts/generate_enhancements.py) || \
    echo "  ⚠ Enhancements regeneration failed — continuing deploy with existing content."
else
  echo "  ⚠ No backend/.venv found — skipping (existing enhancements_data.json ships as-is)."
fi

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
  --memory 2Gi \
  --cpu 1 \
  --timeout 600 \
  --set-secrets "ANTHROPIC_API_KEY=rep-assist-anthropic-key:latest,LANGCHAIN_API_KEY=rep-assist-langsmith-key:latest,SMTP_PASSWORD=rep-assist-smtp-password:latest,ADMIN_TOKEN=rep-assist-admin-token:latest" \
  --set-env-vars "LANGCHAIN_PROJECT=rep-assist,ANTHROPIC_MODEL=claude-sonnet-5,SMTP_HOST=smtp.gmail.com,SMTP_PORT=587,SMTP_USER=milhon@gmail.com,SMTP_FROM=Grady Milhon <milhon@gmail.com>,SMTP_TLS=true"

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
