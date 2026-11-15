from os import environ
from .env import env_number


class AppConfig:
    AUTH_TRUSTED_PROXY_CIDRS = environ.get('AUTH_TRUSTED_PROXY_CIDRS', '')
    AUTH_MAX_FAILURES = env_number('AUTH_MAX_FAILURES', 5, minimum=1, maximum=100, integer=True)
    AUTH_WINDOW_SECONDS = env_number('AUTH_WINDOW_SECONDS', 60, minimum=1, maximum=3600, integer=True)
    MONGODB_URI = environ.get('MONGODB_URI', '')
    MONGODB_DATABASE = environ.get('MONGODB_DATABASE', 'aws_monitor')
    APP_HOST = environ.get('APP_HOST', '127.0.0.1')
    AWS_REGION = environ.get('AWS_REGION', 'us-east-1')
    AWS_CACHE_TTL = env_number('AWS_CACHE_TTL', 30, minimum=0, maximum=86400)
    AWS_REFRESH_TIMEOUT = env_number('AWS_REFRESH_TIMEOUT', 3, minimum=0, maximum=30)
    AWS_FAILURE_COOLDOWN = env_number('AWS_FAILURE_COOLDOWN', 10, minimum=0, maximum=3600)
    AWS_TASK_TIMEOUT = env_number('AWS_TASK_TIMEOUT', 15, minimum=0.1, maximum=300)
    AWS_MAX_DATA_AGE = env_number('AWS_MAX_DATA_AGE', 900, minimum=1, maximum=86400)
