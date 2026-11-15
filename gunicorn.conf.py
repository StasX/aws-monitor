from os import environ
from app.utils.env import env_number

bind = f"{environ.get('APP_HOST', '0.0.0.0')}:5001"
workers = env_number('WEB_CONCURRENCY', 2, minimum=1, maximum=32, integer=True)
worker_class = 'gthread'
threads = env_number('GUNICORN_THREADS', 4, minimum=1, maximum=64, integer=True)
timeout = 60
graceful_timeout = 30
accesslog = '-'
errorlog = '-'
capture_output = True
# The container root filesystem is read-only in Kubernetes.
worker_tmp_dir = '/dev/shm'
