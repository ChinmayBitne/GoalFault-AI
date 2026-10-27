# Deployment

GoalFault is a small CPU-only Python service, so a single container on Google Cloud Run is enough. The included `Dockerfile` serves the app on `$PORT` (default 8080).

## Read this first

- **Storage is not durable on Cloud Run.** SQLite lives on the container filesystem and disappears when an instance stops or a new revision ships. Use Firestore or Cloud SQL before relying on hosted run history.
- **Writes are refused on Cloud Run unless `GOALFAULT_ADMIN_TOKEN` is set**, and even then a single shared token is not proper auth. Keep the service private, or offer a read-only public view alongside a recorded live run.
- **Never expose an open endpoint that spends Meta credits.**

## Deploying privately

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com

# Create secrets for MODEL_API_KEY and GOALFAULT_ADMIN_TOKEN in Secret Manager
# and give the Cloud Run service account access to them.

gcloud run deploy goalfault-ai --source . --region us-west1 \
  --no-allow-unauthenticated --min-instances 0 --max-instances 1 --concurrency 1
```

Attach the two secrets to the service as environment variables. Don't pass secret values on the command line, because they end up in shell history and build logs.

One instance with a concurrency of 1 keeps both hosting costs and parallel model spend predictable.

## Target setup for a public demo

```text
Cloud Run (API + static UI)
  ├── Meta Model API   (key from Secret Manager)
  ├── Firestore        (scenarios, approvals, runs)
  ├── Secret Manager   (API key, admin token)
  └── Cloud Logging    (synthetic data only, no secrets)
```

## Costs

- Set Cloud Billing budget alerts, for example at $5, $15 and $30.
- Cloud credits do not pay for Meta Model API usage. Track the two separately.
- Delete the service when it's no longer needed.

Reference: [Deploy a FastAPI service to Cloud Run](https://cloud.google.com/run/docs/quickstarts/build-and-deploy/deploy-python-fastapi-service).
