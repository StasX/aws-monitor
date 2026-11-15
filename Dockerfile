FROM python:3.14.4-alpine3.23 AS builder
WORKDIR /app
RUN python -m venv /app/env && \
    /app/env/bin/pip install --upgrade pip
COPY requirements.txt .
RUN /app/env/bin/pip install --no-cache-dir -r requirements.txt


FROM python:3.14.4-alpine3.23
ENV APP_HOST="0.0.0.0" \
    APP_PORT="5001"
WORKDIR /app
RUN apk update && \
    apk upgrade --no-cache && \
    apk add --no-cache curl && \
    python -m pip install --upgrade pip
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
COPY --from=builder /app/env /app/env
COPY . .
RUN chown -R appuser:appgroup /app
USER appuser
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f "http://localhost:${APP_PORT:-5001}/health" || exit 1
ENTRYPOINT ["/app/env/bin/gunicorn", "--config", "gunicorn.conf.py", "app.app:create_app()"]
EXPOSE ${APP_PORT}
