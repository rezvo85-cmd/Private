RONN CORE - RENDER DEPLOYMENT

Canonical deployment configuration:
  Repository root: render.yaml
  Core application: RONN_CORE_RENDER_DEPLOY_V1/_ronn/
  Render service: RONN_CORE
  Render database: RONN_MEMORY (PostgreSQL 18)
  Runtime: Python
  Build command: pip install -r requirements.txt
  Start command: uvicorn app:app --host 0.0.0.0 --port $PORT
  Health check: /health

The root render.yaml is the source of truth for Render Blueprint deployments.
RONN_CORE_RENDER_DEPLOY_V1/render.yaml is kept in sync for compatibility with
workflows and tooling that inspect the deployment configuration from the
application folder. Do not give the two files different service names, root
directories, database bindings, or runtime settings.

Required private Render environment configuration:
  CLOUD_API_KEY = provider API key (keep it in Render, never in Git)
  RONN_CORE_TOKEN = long random server-side secret
  RONN_PUBLIC_MODE = true only when unauthenticated device-scoped public chat
                     is intentionally enabled; otherwise set false
  RONN_CORS_ORIGINS = exact trusted web/PWA origins, comma-separated

The Render Blueprint binds DATABASE_URL to the RONN_MEMORY PostgreSQL
connection string. Keep the database in the same region as RONN_CORE.

Never commit a real .env file, API key, database URL, owner recovery code,
or signing secret. Configure secrets in Render's environment settings.
Do not rely on the service's ephemeral local filesystem for persistent user
memory or durable application data. Core conversation and memory storage use
the configured PostgreSQL database; optional local caches and diagnostics may
be recreated after a deploy.

After changing the Blueprint, review the proposed Render changes before
applying them. Do not recreate or delete the existing RONN_MEMORY database.
