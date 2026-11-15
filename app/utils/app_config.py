from os import environ
from .env import env_number


class AppConfig:
    DASHBOARD_USERNAME = environ.get('DASHBOARD_USERNAME', '')
    DASHBOARD_PASSWORD_HASH = environ.get('DASHBOARD_PASSWORD_HASH', '')
    APP_HOST = environ.get('APP_HOST', '127.0.0.1')
    AWS_REGION = environ.get('AWS_REGION', 'us-east-1')
    AWS_CACHE_TTL = env_number('AWS_CACHE_TTL', 30, minimum=0, maximum=86400)
    AWS_REFRESH_TIMEOUT = env_number('AWS_REFRESH_TIMEOUT', 3, minimum=0, maximum=30)
    AWS_FAILURE_COOLDOWN = env_number('AWS_FAILURE_COOLDOWN', 10, minimum=0, maximum=3600)
    AWS_TASK_TIMEOUT = env_number('AWS_TASK_TIMEOUT', 15, minimum=0.1, maximum=300)
    AWS_MAX_DATA_AGE = env_number('AWS_MAX_DATA_AGE', 900, minimum=1, maximum=86400)
