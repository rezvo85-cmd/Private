RONN CORE - RENDER DEPLOY V1

GitHub repository contents:
  _ronn/
  render.yaml
  .gitignore
  .env.example
  DEPLOY_README.txt

DO NOT upload a real .env file or API keys to GitHub.

Manual Render settings:
  Runtime: Python
  Root Directory: _ronn
  Build Command: pip install -r requirements.txt
  Start Command: uvicorn app:app --host 0.0.0.0 --port $PORT
  Health Check Path: /api/v1/health

Environment variables to set privately in Render:
  CLOUD_API_KEY = your Groq key
  CLOUD_API_BASE = https://api.groq.com/openai/v1
  RONN_CORE_TOKEN = a new long random private token
  RONN_PUBLIC_MODE = true

RONN_CORS_ORIGINS can be set after the web/PWA URL exists.
For the first backend test, leave it blank. Later set it to the exact PWA origin.

Important: Render's ordinary filesystem is ephemeral. This first deployment is for getting Core online. Persistent cloud chat/memory should use a persistent database/disk before relying on it as permanent storage.
