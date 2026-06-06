FROM python:3.14.4-alpine3.22
WORKDIR /app
RUN apk update && \
    apk upgrade && \
    python -m venv env
COPY requirements.txt .
RUN /app/env/bin/pip install -r requirements.txt
COPY . .
ENTRYPOINT ["/app/env/bin/python", "-m", "flask", "--app", "app.py", "run", "--host=0.0.0.0", "--port=5001"]
EXPOSE 5001
