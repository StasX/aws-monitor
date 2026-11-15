from flask import Flask
from .logic.resources_cache import ResourcesCache

from .utils.app_config import AppConfig
from .utils.metrics import RequestMetrics
from .utils.auth_throttle import AuthThrottle
from .utils.mongodb import MongoDB
from .logic.users_logic import UsersLogic
from .repositories.user_repository import UserRepository
from .utils.user_commands import register_user_commands
from .views.monitoring_view import monitoring_blueprint
from .views.resources_view import resources_blueprint


def create_app():
    application = Flask(__name__)
    application.config.from_object(AppConfig)
    store = MongoDB(application.config['MONGODB_URI'], application.config['MONGODB_DATABASE'])
    application.extensions['mongodb'] = store
    application.extensions['auth_throttle'] = AuthThrottle(store=store)
    application.extensions['users'] = UsersLogic(UserRepository(store))
    register_user_commands(application)
    application.extensions['request_metrics'] = RequestMetrics(application)
    application.extensions['resources_cache'] = ResourcesCache(logger=application.logger)
    application.register_blueprint(resources_blueprint)
    application.register_blueprint(monitoring_blueprint)
    return application


def main():
    app = create_app()
    app.run(host=app.config['APP_HOST'], port=5001, debug=False)


if __name__ == '__main__':
    main()
