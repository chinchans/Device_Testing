# Optional path: custom AppSail runtime (requires Docker).
# Preferred without Docker: Catalyst-managed Python — see DEPLOY.md
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV MONITOR_STORE=sqlite
ENV PYTHONUNBUFFERED=1

EXPOSE 9000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${X_ZOHO_CATALYST_LISTEN_PORT:-9000}"]
