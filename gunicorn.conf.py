from os import environ
from pathlib import Path

# Supplied by the runtime environment before importing prometheus_client.
metrics_directory = Path(environ['PROMETHEUS_MULTIPROC_DIR'])

from app.utils.env import env_number

port = env_number('APP_PORT', 5001, minimum=1, maximum=65535, integer=True)
bind = f"{environ['APP_HOST']}:{port}"
workers = env_number('WEB_CONCURRENCY', 2, minimum=1, maximum=32, integer=True)
worker_class = 'gthread'
threads = env_number('GUNICORN_THREADS', 4, minimum=1, maximum=64, integer=True)
timeout = 60
graceful_timeout = 30
accesslog = '-'
errorlog = '-'
capture_output = True
# The container root filesystem is read-only in Kubernetes.
worker_tmp_dir = environ['GUNICORN_WORKER_TMP_DIR']


def on_starting(server):
    # Only this application's dedicated metric files; preserve counters when
    # individual workers restart, reset them when the Gunicorn master restarts.
    metrics_directory.mkdir(parents=True, exist_ok=True)
    for metric_file in metrics_directory.glob('*.db'):
        metric_file.unlink()


def child_exit(server, worker):
    from prometheus_client import multiprocess
    multiprocess.mark_process_dead(worker.pid)
