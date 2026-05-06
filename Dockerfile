FROM python:3.14.4
WORKDIR /app
RUN python -m venv env
COPY requirements.txt .
RUN /app/env/bin/pip install -r requirements.txt
COPY . .
ENV AWS_ACCESS_KEY_ID=None
ENV AWS_SECRET_ACCESS_KEY=None
ENTRYPOINT ["/app/env/bin/python", "-m", "flask", "--app", "app.py", "run", "--host=0.0.0.0", "--port=5001"]
EXPOSE 5001