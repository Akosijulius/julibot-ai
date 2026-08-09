# Procfile for Render / Heroku-style deployments.
# Render: use "start" as the Start Command.
web: uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers "${WORKERS:-1}"
