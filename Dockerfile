FROM python:3.14.4-alpine3.22
RUN apk update && \
    apk upgrade && \
    apk add --no-cache curl
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
WORKDIR /app
RUN python -m venv env
COPY requirements.txt .
RUN /app/env/bin/pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chown -R appuser:appgroup /app
USER appuser
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:5001/health || exit 1
ENTRYPOINT ["sh", "-c", "exec /app/env/bin/python -m flask --app app.py run --host=$APP_HOST --port=5001"]
EXPOSE 5001